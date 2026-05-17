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

def _verify_enc_key(enc_key: bytes, page0: bytes) -> bool:
    """验证 enc_key 是否为该数据库的有效密钥（HMAC-SHA512 校验）"""
    import hmac as _hmac

    salt = page0[:16]
    mac_salt = bytes(b ^ 0x3A for b in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=32)

    hmac_data = page0[16:4096 - 80 + 16]  # page0[16:4032]
    stored_hmac = page0[4096 - 64:4096]   # page0[4032:4096]

    hm = _hmac.new(mac_key, hmac_data, hashlib.sha512)
    hm.update(struct.pack("<I", 1))
    return hm.digest() == stored_hmac


def _extract_keys_v4(db_files: dict[str, Path]) -> dict[str, str]:
    """从 Weixin.exe 进程的全部可读内存中提取每个数据库的 SQLCipher 4 密钥

    使用 ctypes 调用 Windows API (VirtualQueryEx / ReadProcessMemory) 遍历
    进程的所有已提交可读内存区域，搜索 x'<hex>' 模式。
    """
    import ctypes
    import ctypes.wintypes as wt
    import re

    PAGE_SIZE = 4096

    # 1) 收集所有数据库的 salt
    db_salts: dict[bytes, tuple[str, bytes]] = {}
    for db_name, db_path in db_files.items():
        if not db_path.exists():
            continue
        with open(db_path, "rb") as f:
            page0 = f.read(PAGE_SIZE)
        if len(page0) < PAGE_SIZE:
            continue
        db_salts[page0[:16]] = (db_name, page0)

    if not db_salts:
        raise RuntimeError("没有可解密的数据库文件")

    # 2) 找到所有 Weixin.exe 进程 PID（按内存占用降序）
    import psutil

    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        if p.info["name"] == "Weixin.exe":
            rss = p.info["memory_info"].rss if p.info["memory_info"] else 0
            procs.append((p.info["pid"], rss))
    procs.sort(key=lambda x: x[1], reverse=True)
    pids: list[int] = [pid for pid, _ in procs]
    if not pids:
        raise RuntimeError("未找到 Weixin.exe 进程，请先登录微信")

    # 3) Windows API 定义
    kernel32 = ctypes.windll.kernel32

    PROCESS_VM_READ = 0x0010
    PROCESS_QUERY_INFORMATION = 0x0400
    MEM_COMMIT = 0x1000
    READABLE_PROTECTS = {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80}

    class MBI(ctypes.Structure):
        _fields_ = [
            ("BaseAddress", ctypes.c_uint64),
            ("AllocationBase", ctypes.c_uint64),
            ("AllocationProtect", wt.DWORD),
            ("_pad1", wt.DWORD),
            ("RegionSize", ctypes.c_uint64),
            ("State", wt.DWORD),
            ("Protect", wt.DWORD),
            ("Type", wt.DWORD),
            ("_pad2", wt.DWORD),
        ]

    key_pattern = re.compile(rb"x'([0-9a-fA-F]{64,192})'")
    CHUNK = 64 * 1024 * 1024  # 64 MB per read

    keys: dict[str, str] = {}
    seen_keys: set[str] = set()

    # 4) 逐进程扫描全部内存区域
    for pid in pids:
        handle = kernel32.OpenProcess(
            PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid
        )
        if not handle:
            continue

        try:
            addr_val = 0
            mbi = MBI()

            while addr_val < 0x7FFFFFFFFFFF:
                mbi = MBI()
                ret = kernel32.VirtualQueryEx(
                    handle, ctypes.c_void_p(addr_val), ctypes.byref(mbi), ctypes.sizeof(mbi)
                )
                if ret != ctypes.sizeof(mbi):
                    break

                # 只扫描已提交的可读区域，跳过超大区域
                if (
                    mbi.State == MEM_COMMIT
                    and mbi.Protect in READABLE_PROTECTS
                    and 0 < mbi.RegionSize < 500 * 1024 * 1024
                ):
                    region_base = mbi.BaseAddress
                    region_size = mbi.RegionSize

                    for offset in range(0, region_size, CHUNK):
                        read_size = min(CHUNK, region_size - offset)
                        buf = (ctypes.c_ubyte * read_size)()
                        n_read = ctypes.c_size_t()

                        ok = kernel32.ReadProcessMemory(
                            handle,
                            ctypes.c_void_p(region_base + offset),
                            buf,
                            read_size,
                            ctypes.byref(n_read),
                        )
                        if not ok or n_read.value == 0:
                            continue

                        data = bytes(buf)[: n_read.value]

                        for m in key_pattern.finditer(data):
                            hex_str = m.group(1).decode("ascii")
                            hex_len = len(hex_str)
                            if hex_len < 64 or hex_len % 2 != 0:
                                continue

                            enc_key_hex = hex_str[:64]

                            if enc_key_hex in seen_keys:
                                continue
                            seen_keys.add(enc_key_hex)

                            if hex_len == 64:
                                continue

                            enc_key = bytes.fromhex(enc_key_hex)

                            if hex_len == 96:
                                salt_hex = hex_str[64:]
                            else:
                                salt_hex = hex_str[-32:]

                            salt_bytes = bytes.fromhex(salt_hex)
                            matched = db_salts.get(salt_bytes)
                            if not matched:
                                continue

                            db_name, page0 = matched
                            if db_name in keys:
                                continue

                            if _verify_enc_key(enc_key, page0):
                                keys[db_name] = enc_key_hex
                                print(f"  + {db_name}: key found (PID {pid})")

                # 移动到下一个区域
                nxt = mbi.BaseAddress + mbi.RegionSize
                if nxt <= addr_val:
                    break
                addr_val = nxt

        finally:
            kernel32.CloseHandle(handle)

        # 如果所有数据库都找到密钥了，提前退出
        if len(keys) == len(db_salts):
            break

    # 5) 对 salt 未匹配的密钥做交叉验证
    if len(keys) < len(db_salts):
        unmatched_salts = {
            s: (n, p) for s, (n, p) in db_salts.items() if n not in keys
        }
        for enc_key_hex in seen_keys:
            if len(unmatched_salts) == 0:
                break
            enc_key = bytes.fromhex(enc_key_hex)
            for salt_bytes, (db_name, page0) in list(unmatched_salts.items()):
                if _verify_enc_key(enc_key, page0):
                    keys[db_name] = enc_key_hex
                    del unmatched_salts[salt_bytes]
                    print(f"  + {db_name}: key found (cross-verify)")

    # 报告未找到密钥的数据库
    for salt_bytes, (db_name, _) in db_salts.items():
        if db_name not in keys:
            print(f"  X {db_name}: key not found")

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
    """解密微信 4.x 数据库（SQLCipher 4，AES-256-CBC，80 字节保留区）

    key_hex 是从内存中提取的 enc_key（已派生好的 32 字节 AES 密钥）。
    输出保持 4096 字节/页：解密数据 + 80 字节零填充保留区。
    """
    from Crypto.Cipher import AES

    PAGE_SIZE = 4096
    RESERVE = 80  # 16 (IV) + 64 (HMAC-SHA512)
    SQLITE_HDR = b"SQLite format 3\x00"

    enc_key = bytes.fromhex(key_hex)

    with open(db_path, "rb") as f:
        data = f.read()

    decrypted = bytearray()
    total_pages = len(data) // PAGE_SIZE

    for page_num in range(total_pages):
        offset = page_num * PAGE_SIZE
        page = data[offset:offset + PAGE_SIZE]

        iv = page[PAGE_SIZE - RESERVE:PAGE_SIZE - RESERVE + 16]

        if page_num == 0:
            encrypted = page[16:PAGE_SIZE - RESERVE]
            dec = AES.new(enc_key, AES.MODE_CBC, iv).decrypt(encrypted)
            decrypted.extend(SQLITE_HDR)
            decrypted.extend(dec)
        else:
            encrypted = page[0:PAGE_SIZE - RESERVE]
            dec = AES.new(enc_key, AES.MODE_CBC, iv).decrypt(encrypted)
            decrypted.extend(dec)

        # 每页补齐 80 字节保留区（填零），保持 4096 字节/页
        decrypted.extend(b"\x00" * RESERVE)

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
                print(f"  + {name}")
            except Exception as e:
                print(f"  X {name}: {e}")
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
                print(f"  + {name}")
            except Exception as e:
                print(f"  X {name}: {e}")

    return decrypted
