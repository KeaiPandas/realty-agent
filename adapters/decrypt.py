"""
解密微信本地数据库
使用 PyWxDump 获取密钥并解密数据库文件
"""
import os
import shutil
import sqlite3
import struct
from pathlib import Path


def get_wx_info():
    """获取微信账号信息和数据库密钥"""
    try:
        from pywxdump import get_wx_info
        info = get_wx_info(is_print=False)
        if info:
            return info
    except Exception:
        pass

    # 备用方案：直接用 pymem 从内存中提取密钥
    return _get_key_from_memory()


def _find_wechat_process():
    """查找微信主进程（兼容不同版本的进程名）"""
    import pymem
    # 新版微信使用 Weixin.exe，旧版使用 WeChat.exe，渲染进程为 WeChatAppEx.exe
    for name in ("Weixin.exe", "WeChat.exe", "WeChatAppEx.exe"):
        try:
            return pymem.Pymem(name)
        except Exception:
            continue
    raise RuntimeError(
        "未找到微信进程，请确保微信已登录并运行。"
        "如果仍无法检测，请在 config/wechat.yaml 中手动配置 data_dir"
    )


def _get_key_from_memory():
    """从微信进程内存中提取数据库密钥"""
    import pymem
    import pymem.process

    pm = _find_wechat_process()

    # 查找 WeChatWin.dll
    wechat_win = None
    for module in pymem.process.enum_process_module(pm.process_handle):
        if "WeChatWin" in module.name:
            wechat_win = module
            break

    if not wechat_win:
        raise RuntimeError("未找到 WeChatWin.dll，请确认微信已启动")

    base = wechat_win.lpBaseOfDll
    size = wechat_win.SizeOfImage
    data = pm.read_bytes(base, size)

    # 搜索特征码定位密钥偏移
    # 微信 3.9.x 的密钥特征：在特定函数序言附近
    # 搜索模式: E8 XX XX XX XX 84 C0 75 XX (调用密钥验证函数)
    key = None

    # 尝试使用 pywxdump 的偏移表
    try:
        from pywxdump.wx_core import BiasAddr
        from pywxdump.wx_core.wx_info import get_wx_info_by_bias
        info = get_wx_info_by_bias(base, BiasAddr)
        if info and len(info) > 0:
            return info
    except Exception:
        pass

    raise RuntimeError("无法提取密钥，请尝试：1. 确保微信已登录 2. 使用 pywxdump CLI 工具手动获取密钥")


def decrypt_db(db_path, key, output_path):
    """解密单个数据库文件

    Args:
        db_path: 加密的数据库路径
        key: 32字节十六进制密钥字符串
        output_path: 解密后的输出路径
    """
    try:
        from pywxdump import decrypt
        return decrypt(db_path, key, output_path)
    except Exception:
        pass

    # 备用方案：手动解密
    return _manual_decrypt(db_path, key, output_path)


def _manual_decrypt(db_path, key_hex, output_path):
    """手动解密微信 SQLite 数据库 (sqlcipher 格式)"""
    from Crypto.Cipher import AES
    import hashlib

    key = bytes.fromhex(key_hex)

    with open(db_path, "rb") as f:
        data = f.read()

    # 微信数据库使用 AES-256-CBC 加密
    # 第一页 (4096 字节) 的前 16 字节是 IV
    page_size = 4096
    iv = data[:16]

    # 使用 HMAC-SHA512 派生密钥
    derived = hashlib.pbkdf2_hmac("sha512", key, iv, 64000, dklen=48)
    aes_key = derived[:32]
    hmac_key = derived[32:48] + derived[32:48]

    cipher = AES.new(aes_key, AES.MODE_CBC, iv)
    decrypted = bytearray()

    for page_num in range(len(data) // page_size):
        offset = page_num * page_size
        page = data[offset:offset + page_size]

        if page_num == 0:
            # 第一页的特殊处理
            page_iv = data[:16]
            page_cipher = AES.new(aes_key, AES.MODE_CBC, page_iv)
            dec_page = page_cipher.decrypt(page[16:])
            decrypted.extend(b"SQLite format 3\x00")
            decrypted.extend(dec_page[16:])
        else:
            page_iv = page[:16]
            page_cipher = AES.new(aes_key, AES.MODE_CBC, page_iv)
            dec_page = page_cipher.decrypt(page[16:])
            decrypted.extend(page[:16])
            decrypted.extend(dec_page)

    with open(output_path, "wb") as f:
        f.write(decrypted)

    return True


def decrypt_all_databases(config):
    """解密所有需要的数据库文件

    Args:
        config: 配置字典

    Returns:
        dict: 解密后的数据库路径 {名称: 路径}
    """
    wechat_dir = config.get("wechat", {}).get("data_dir", "")
    if not wechat_dir:
        # 自动检测：从微信进程获取数据目录
        wx_info = get_wx_info()
        if isinstance(wx_info, list) and wx_info:
            wechat_dir = wx_info[0].get("wx_dir", "")
        if not wechat_dir:
            raise RuntimeError("无法自动检测微信数据目录，请在 config/wechat.yaml 中配置 data_dir")
    wechat_dir = Path(wechat_dir)
    msg_dir = wechat_dir / "Msg"
    output_dir = wechat_dir / "decrypted"
    output_dir.mkdir(exist_ok=True)

    # 获取密钥
    print("[1/4] 获取微信密钥...")
    wx_info = get_wx_info()

    if isinstance(wx_info, list) and len(wx_info) > 0:
        # PyWxDump 返回的是列表
        info = wx_info[0]
        key = info.get("key", "")
    else:
        raise RuntimeError("未能获取密钥")

    if not key:
        raise RuntimeError("密钥为空")

    print(f"  密钥: {key[:8]}...")

    # 需要解密的数据库文件
    try:
        from config import settings
        db_names = settings.WECHAT_DB_NAMES + ["ChatRoomUser", "Misc"]
    except Exception:
        db_names = ["MicroMsg", "ChatMsg", "ChatRoomUser", "Misc"]

    db_files = {name: msg_dir / f"{name}.db" for name in db_names}

    # 添加 MSG 多分片文件
    multi_dir = msg_dir / "Multi"
    if multi_dir.exists():
        for f in sorted(multi_dir.glob("MSG*.db")):
            db_files[f.stem] = f

    # 解密
    print(f"[2/4] 解密 {len(db_files)} 个数据库...")
    decrypted = {}
    for name, db_path in db_files.items():
        if not db_path.exists():
            continue
        out_path = output_dir / f"{name}.db"
        try:
            decrypt_db(str(db_path), key, str(out_path))
            decrypted[name] = str(out_path)
            print(f"  ✓ {name}")
        except Exception as e:
            print(f"  ✗ {name}: {e}")

    return decrypted


if __name__ == "__main__":
    import yaml

    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    result = decrypt_all_databases(config)
    print(f"\n解密完成，共 {len(result)} 个数据库")
    for name, path in result.items():
        print(f"  {name}: {path}")
