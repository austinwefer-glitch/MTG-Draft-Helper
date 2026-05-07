"""
Inspect the first ~200 bytes of the MTGA data files to figure out
their actual format. They might be plain JSON, gzip, zlib, or a
custom binary format.
"""

from pathlib import Path

DATA_DIR = Path(r"C:\Program Files\Wizards of the Coast\MTGA\MTGA_Data\Downloads\Raw")


def inspect(path: Path) -> None:
    print("=" * 70)
    print(f"File: {path.name}")
    print(f"Size: {path.stat().st_size:,} bytes")
    raw = path.read_bytes()[:256]
    print(f"\nFirst 64 bytes (hex):")
    for i in range(0, 64, 16):
        chunk = raw[i:i+16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"  {i:04x}: {hex_part:<48}  {ascii_part}")

    # Identify common formats
    print()
    if raw.startswith(b"\x1f\x8b"):
        print("Detected: gzip-compressed")
    elif raw[:4] in (b"\x04\x22\x4d\x18", b"PK\x03\x04"):
        print("Detected: LZ4 or ZIP archive")
    elif raw.startswith(b"\x78\x9c") or raw.startswith(b"\x78\xda"):
        print("Detected: zlib-compressed")
    elif raw.startswith(b"{"):
        print("Detected: starts with '{', looks like JSON")
    elif raw.startswith(b"["):
        print("Detected: starts with '[', looks like JSON array")
    else:
        print(f"Unknown signature. First 4 bytes: {raw[:4].hex()}")


if __name__ == "__main__":
    for name in ["Raw_ClientLocalization_405e991af0a27c163db2b7a0e0a09c07.mtga",
                 "Raw_CardDatabase_c8cab57af7d1f0182cab54633c99f859.mtga"]:
        p = DATA_DIR / name
        if p.exists():
            inspect(p)
        else:
            print(f"Missing: {p}")
