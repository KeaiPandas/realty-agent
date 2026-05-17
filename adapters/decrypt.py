"""
解密微信本地数据库
支持 WeChat 3.x（pywxdump）和 WeChat 4.x（SQLCipher 4 内存密钥提取）
"""
import hashlib
import struct
from pathlib import Path


# ── 版本检测 ──────────────────────────────────────────────

def _resolve_version() -> str:
    """获取微信版本（配置优先，否则自动检测）"""
    from config import settings
    v = settings.WECHAT_VERSION
    if v and v != "auto":
        return v
    return _detect_version()


def _detect_version() -> str:
    """基于进程名自动检测微信版本"""
    import psutil
    for p in psutil.process_iter(["name"]):
        name = p.info.get("name", "")
        if name == "Weixin.exe":
            return "4.x"
        if name == "WeChat.exe":
            return "3.x"
    raise RuntimeError("未检测到微信进程，请先登录微信")


# ── 3.x 密钥提取 ──────────────────────────────────────────

def _get_wx_info_v3():
    """获取微信 3.x 账号信息和数据库密钥"""
    try:
        from pywxdump import get_wx_info
        info = get_wx_info(is_print=False)
        if info:
            return info
    except Exception:
        pass

    return _get_key_from_memory_v3()


def _get_key_from_memory_v3():
    """从微信 3.x 进程内存中提取数据库密钥"""
    import pymem
    import pymem.process

    pm = _attach_wechat()
    wechat_win = None
    for module in pymem.process.enum_process_module(pm.process_handle):
        if "WeChatWin" in module.name or "Weixin" in module.name:
            wechat_win = module
            break

    if not wechat_win:
        raise RuntimeError("未找到微信核心 DLL，请确认微信已启动")

    base = wechat_win.lpBaseOfDll

    try:
        from pywxdump.wx_core import BiasAddr
        from pywxdump.wx_core.wx_info import get_wx_info_by_bias
        info = get_wx_info_by_bias(base, BiasAddr)
        if info and len(info) > 0:
            return info
    except Exception:
        pass

    raise RuntimeError("无法提取 3.x 密钥，请确保微信版本 <= 3.9.x")


def _attach_wechat():
    """附加到微信进程"""
    import pymem
    for name in ("Weixin.exe", "WeChat.exe", "WeChatAppEx.exe"):
        try:
            return pymem.Pymem(name)
        except Exception:
            continue
    raise RuntimeError("未找到微信进程，请确保微信已登录并运行")


# ── 4.x 密钥提取 ──────────────────────────────────────────

def _extract_keys_v4(db_files: dict[str, Path]) -> dict[str, str]:
    """从 Weixin.exe 进程内存中提取每个数据库的 SQLCipher 4 密钥

    扫描 Weixin.dll 内存区域，查找 64 字符十六进制模式，
    通过 HMAC-SHA512 校验验证密钥是否对某个数据库有效。
    """
    import pymem
    import pymem.process
    import re
    from Crypto.Cipher import AES

    pm = pymem.Pymem("Weixin.exe")

    # 找 Weixin.dll
    weixin_dll = None
    for module in pymem.process.enum_process_module(pm.process_handle):
        if module.name == "Weixin.dll":
            weixin_dll = module
            break

    if not weixin_dll:
        raise RuntimeError("未找到 Weixin.dll")

    # 分块读取 DLL 内存（太大不能一次读）
    base = weixin_dll.lpBaseOfDll
    size = weixin_dll.SizeOfImage
    CHUNK = 64 * 1024 * 1024  # 64MB per read

    # 收集所有候选密钥（64 字符十六进制串）
    candidates: list[bytes] = []
    hex_pattern = re.compile(rb"[0-9a-fA-F]{64}")

    for offset in range(0, size, CHUNK):
        chunk_size = min(CHUNK, size - offset)
        try:
            data = pm.read_bytes(base + offset, chunk_size)
            for m in hex_pattern.finditer(data):
                candidates.append(m.group())
        except Exception:
            continue

    if not candidates:
        raise RuntimeError("未在 Weixin.dll 内存中找到候选密钥")

    # 对每个数据库，验证候选密钥
    PAGE_SIZE = 4096
    keys: dict[str, str] = {}

    for db_name, db_path in db_files.items():
        if not db_path.exists():
            continue

        with open(db_path, "rb") as f:
            page0 = f.read(PAGE_SIZE)
        if len(page0) < PAGE_SIZE:
            continue

        salt = page0[:16]
        mac_salt = bytes(b ^ 0x3a for b in salt)

        found = False
        for candidate in candidates:
            raw_key = bytes.fromhex(candidate.decode("ascii"))
            if len(raw_key) != 32:
                continue

            # 派生 HMAC 密钥
            mac_key = hashlib.pbkdf2_hmac("sha512", raw_key, mac_salt, 2, dklen=32)

            # 计算第 0 页的 HMAC（不含 salt 和保留区域）
            page_data = page0[16:PAGE_SIZE - 80]
            iv = page0[PAGE_SIZE - 80:PAGE_SIZE - 64]
            stored_hmac = page0[PAGE_SIZE - 64:PAGE_SIZE]

            import hmac as _hmac
            computed = _hmac.new(mac_key, page_data + iv, hashlib.sha512).digest()

            if computed == stored_hmac:
                keys[db_name] = candidate.decode("ascii")
                found = True
                break

        if not found:
            print(f"  ✗ {db_name}: 未找到有效密钥")

    return keys


# ── 3.x 解密 ──────────────────────────────────────────────

def _decrypt_db_v3(db_path, key_hex, output_path):
    """解密微信 3.x 数据库（sqlcipher，PBKDF2 64000 迭代）"""
    try:
        from pywxdump import decrypt
        return decrypt(db_path, key_hex, output_path)
    except Exception:
        pass

    from Crypto.Cipher import AES

    key = bytes.fromhex(key_hex)
    with open(db_path, "rb") as f:
        data = f.read()

    page_size = 4096
    iv = data[:16]
    derived = hashlib.pbkdf2_hmac("sha512", key, iv, 64000, dklen=48)
    aes_key = derived[:32]

    decrypted = bytearray()
    for page_num in range(len(data) // page_size):
        offset = page_num * page_size
        page = data[offset:offset + page_size]

        if page_num == 0:
            page_cipher = AES.new(aes_key, AES.MODE_CBC, iv)
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


# ── 4.x 解密 ──────────────────────────────────────────────

def _decrypt_db_v4(db_path, key_hex, output_path):
    """解密微信 4.x 数据库（SQLCipher 4，PBKDF2-HMAC-SHA512 256000 迭代，80 字节保留区）"""
    import hmac as _hmac
    from Crypto.Cipher import AES

    PAGE_SIZE = 4096
    RESERVE = 80  # 16 (IV) + 64 (HMAC-SHA512)

    raw_key = bytes.fromhex(key_hex)

    with open(db_path, "rb") as f:
        data = f.read()

    salt = data[:16]
    mac_salt = bytes(b ^ 0x3a for b in salt)

    # 派生加密密钥和 HMAC 密钥
    enc_key = hashlib.pbkdf2_hmac("sha512", raw_key, salt, 256000, dklen=32)
    mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=32)

    decrypted = bytearray()
    total_pages = len(data) // PAGE_SIZE

    for page_num in range(total_pages):
        offset = page_num * PAGE_SIZE
        page = data[offset:offset + PAGE_SIZE]

        if page_num == 0:
            page_salt = page[:16]
            page_enc_key = hashlib.pbkdf2_hmac(
                "sha512", raw_key, page_salt, 256000, dklen=32
            )
            iv = page[PAGE_SIZE - RESERVE:PAGE_SIZE - RESERVE + 16]
            encrypted = page[16:PAGE_SIZE - RESERVE]
            cipher = AES.new(page_enc_key, AES.MODE_CBC, iv)
            dec = cipher.decrypt(encrypted)
            decrypted.extend(b"SQLite format 3\x00")
            decrypted.extend(dec)
        else:
            iv = page[PAGE_SIZE - RESERVE:PAGE_SIZE - RESERVE + 16]
            encrypted = page[0:PAGE_SIZE - RESERVE]
            cipher = AES.new(enc_key, AES.MODE_CBC, iv)
            dec = cipher.decrypt(encrypted)
            decrypted.extend(dec)

    with open(output_path, "wb") as f:
        f.write(decrypted)
    return True


# ── 统一入口 ──────────────────────────────────────────────

def decrypt_all_databases(config=None) -> dict[str, str]:
    """解密所有需要的数据库文件

    Returns:
        dict: 解密后的数据库路径 {名称: 路径}
    """
    from config import settings
    from adapters.db_layout import get_db_layout

    version = _resolve_version()
    print(f"[版本] 检测到微信 {version}")

    # 获取数据目录
    wechat_dir = settings.WECHAT_DATA_DIR
    if not wechat_dir:
        if version == "3.x":
            wx_info = _get_wx_info_v3()
            if isinstance(wx_info, list) and wx_info:
                wechat_dir = wx_info[0].get("wx_dir", "")
        # 4.x 必须手动配置 data_dir
        if not wechat_dir:
            raise RuntimeError(
                "无法自动检测微信数据目录，请在 .env 中配置 WECHAT_DATA_DIR\n"
                "  4.x 路径通常类似: D:\\Wechat Files\\xwechat_files\\wxid_xxx\\xxx"
            )

    wechat_dir = Path(wechat_dir)
    output_dir = wechat_dir / "decrypted"
    output_dir.mkdir(exist_ok=True)

    # 获取数据库文件布局
    db_files = get_db_layout(wechat_dir, version)
    if not db_files:
        raise RuntimeError(f"未找到数据库文件，请检查 WECHAT_DATA_DIR={wechat_dir}")

    print(f"[数据库] 找到 {len(db_files)} 个数据库")

    # 获取密钥并解密
    decrypted: dict[str, str] = {}

    if version == "4.x":
        print("[密钥] 从 Weixin.exe 内存提取密钥...")
        keys = _extract_keys_v4(db_files)
        print(f"[密钥] 成功提取 {len(keys)} 个密钥")

        for name, key_hex in keys.items():
            db_path = db_files[name]
            out_path = output_dir / f"{name}.db"
            try:
                _decrypt_db_v4(str(db_path), key_hex, str(out_path))
                decrypted[name] = str(out_path)
                print(f"  ✓ {name}")
            except Exception as e:
                print(f"  ✗ {name}: {e}")
    else:
        # 3.x: 单一密钥
        print("[密钥] 从微信进程提取密钥...")
        wx_info = _get_wx_info_v3()
        if isinstance(wx_info, list) and wx_info:
            key = wx_info[0].get("key", "")
        else:
            raise RuntimeError("未能获取密钥")

        if not key:
            raise RuntimeError("密钥为空")
        print(f"  密钥: {key[:8]}...")

        for name, db_path in db_files.items():
            out_path = output_dir / f"{name}.db"
            try:
                _decrypt_db_v3(str(db_path), key, str(out_path))
                decrypted[name] = str(out_path)
                print(f"  ✓ {name}")
            except Exception as e:
                print(f"  ✗ {name}: {e}")

    return decrypted
