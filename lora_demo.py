import os
import io
import struct
import zlib
from PIL import Image
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ==============================================================================
# 1. KONFIGURASI GLOBAL
# ==============================================================================
SHARED_KEY = b"12345678901234567890123456789012"  # 32 Byte AES-256 Key
MAGIC_HEADER = 0xAA55                              # Sync Word / Identitas Paket (2B)
CHUNK_SIZE = 180                                   # Kapasitas payload radio (Byte)


# ==============================================================================
# 2. HELPER UTILITY (HEXDUMP FORMATTER)
# ==============================================================================
def print_hexdump(byte_data, max_bytes=64, title="HEX DUMP"):
    """
    Format output hexdump standar (Offset | Hex Bytes | ASCII Text)
    """
    print(f"\n--- [{title}] (Menampilkan {min(len(byte_data), max_bytes)} dari {len(byte_data)} Bytes) ---")
    view_data = byte_data[:max_bytes]
    for offset in range(0, len(view_data), 16):
        chunk = view_data[offset:offset+16]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        print(f"{offset:04X}  {hex_part:<48}  |{ascii_part}|")
    if len(byte_data) > max_bytes:
        print(f"... ({len(byte_data) - max_bytes} bytes berikutnya tidak ditampilkan)")


# ==============================================================================
# 3. MESIN KRIPTOGRAFI (AES-256-GCM)
# ==============================================================================
def encryption(rawdata):
    aes = AESGCM(SHARED_KEY)
    nonce = os.urandom(12)
    cipher = aes.encrypt(nonce, rawdata, None)
    return nonce + cipher

def decryption(encryptiondata):
    aes = AESGCM(SHARED_KEY)
    nonce = encryptiondata[:12]
    cipher = encryptiondata[12:]
    return aes.decrypt(nonce, cipher, None)


# ==============================================================================
# 4. MESIN PENGOLAHAN GAMBAR
# ==============================================================================
def compress_and_pack_image(file_path):
    orig_size = os.path.getsize(file_path)
    print(f"\n[Gambar] Ukuran File Asli: {orig_size} bytes ({orig_size / 1024:.2f} KB)")
    
    with open(file_path, "rb") as f:
        print_hexdump(f.read(), max_bytes=48, title="Hex Dump: File Gambar Asli Sebelum Diproses")
    
    # 1. Mode RGB & Resize Proporsional (Maks 240x240 px)
    img = Image.open(file_path).convert('RGB')
    img.thumbnail((240, 240))
    
    # 2. Kompresi JPEG (Quality 50)
    buffer_jpg = io.BytesIO()
    img.save(buffer_jpg, format="JPEG", quality=50)
    jpeg_bytes = buffer_jpg.getvalue()
    
    # 3. Kompresi biner Zlib (Lossless)
    compressed_bytes = zlib.compress(jpeg_bytes, level=9)
    
    print(f"\n[Gambar] Ukuran Setelah Kompresi (RGB + Zlib): {len(compressed_bytes)} bytes ({len(compressed_bytes) / 1024:.2f} KB)")
    print_hexdump(compressed_bytes, max_bytes=48, title="Hex Dump: Payload Terkompresi (Siap Enkripsi)")
    
    return compressed_bytes

def decompress_and_restore_image(raw_bytes, target_file="foto_terima.jpg", upscale_file="foto_upscale.png"):
    # 1. Dekompresi biner Zlib kembali ke byte JPEG mentah
    jpeg_bytes = zlib.decompress(raw_bytes)
    
    # 2. Simpan file JPEG hasil rekonstruksi
    with open(target_file, "wb") as f:
        f.write(jpeg_bytes)
    print(f"\n[Penerima] File JPEG mentah disimpan: '{target_file}' ({len(jpeg_bytes)} bytes)")
    print_hexdump(jpeg_bytes, max_bytes=48, title="Hex Dump: File JPEG Terdekripsi")
    
    # 3. Dekompresi matriks piksel JPEG & Upscale resolusi tampilan
    buffer_in = io.BytesIO(jpeg_bytes)
    img = Image.open(buffer_in)
    img_upscaled = img.resize((480, 480), Image.Resampling.LANCZOS)
    img_upscaled.save(upscale_file)
    print(f"[Penerima] Gambar didekompresi & di-upscale ke: '{upscale_file}' (480x480 px)")
    
    img_upscaled.show()


# ==============================================================================
# 5. PROTOKOL FRAMING PAKET RADIO
# ==============================================================================
def packetPayload(typePacket, dataPayload):
    totalPacket = (len(dataPayload) + CHUNK_SIZE - 1) // CHUNK_SIZE
    listPacket = []

    for order in range(totalPacket):
        startOrder = order * CHUNK_SIZE
        endOrder = startOrder + CHUNK_SIZE
        sliceOrder = dataPayload[startOrder:endOrder]

        # Header: Magic(2B), Type(1B), Total(2B), Order(2B), Length(1B)
        header = struct.pack(">HBHBB", MAGIC_HEADER, typePacket, totalPacket, order, len(sliceOrder))
        listPacket.append(header + sliceOrder)

    return listPacket

def unPackPacket(binaryPacket):
    sizeHeader = struct.calcsize(">HBHBB")
    magic, p_type, total, index, p_len = struct.unpack(">HBHBB", binaryPacket[:sizeHeader])

    if magic != MAGIC_HEADER:
        print("[Peringatan] Magic Header tidak valid / Paket rusak!")
        return None

    slicePacket = binaryPacket[sizeHeader : sizeHeader + p_len]
    return p_type, total, index, slicePacket


# ==============================================================================
# 6. PROGRAM UTAMA
# ==============================================================================
print(f"{15*'='} LORA TRANSCEIVER & HEX INSPECTOR {15*'='}")
choose = input("Pilih Mode Pengiriman (1. Chat Teks, 2. File Gambar): ")

if choose == "1":
    typeData = 1
    massage = input("Ketik Pesan Chat: ")
    realData = massage.encode("utf-8")
    print_hexdump(realData, max_bytes=48, title="Hex Dump: Teks Mentah (UTF-8)")
elif choose == "2":
    typeData = 2
    pathPhoto = input("Masukkan Nama/Path File Gambar (misal: the_numbers.png): ")
    realData = compress_and_pack_image(pathPhoto)
else: 
    print("Mode tidak valid!")
    exit()

# SISI PENGIRIM
print("\n" + "="*15 + " 1. SISI PENGIRIM: ENKRIPSI & FRAMING " + "="*15)
encryptionData = encryption(realData)
print_hexdump(encryptionData, max_bytes=48, title="Hex Dump: Data Terenkripsi AES-GCM (Nonce + Cipher + Tag)")

allPacket = packetPayload(typeData, encryptionData)
total_bytes_sent = sum(len(pkt) for pkt in allPacket)
print(f"\nTotal Transmisi Udara : {total_bytes_sent} bytes ({total_bytes_sent / 1024:.2f} KB)")
print(f"Total Pecahan Paket   : {len(allPacket)} paket")

# Hex Dump Paket Pertama Lengkap (Header + Payload)
print_hexdump(allPacket[0], max_bytes=len(allPacket[0]), title="Hex Dump: Paket Radio #1 Lengkap (Header 8B + Payload)")


# TRANSMISI RADIO (SIMULASI)
transmitted_channel = allPacket


# SISI PENERIMA
print("\n" + "="*15 + " 2. SISI PENERIMA: REASSEMBLY & DEKRIPSI " + "="*15)
packetContainer = {}
totalExpect = 0
typeReceive = 0

for packet in transmitted_channel:
    results = unPackPacket(packet)
    if results is not None:
        typeReceive, totalExpect, order, content = results
        packetContainer[order] = content
        print(f"-> Diterima Paket #{order + 1}/{totalExpect} | Hex Header: {packet[:8].hex().upper()} | Ukuran: {len(packet)}B")

# Rekonstruksi & Dekripsi Payload
dataCombine = b"".join([packetContainer[i] for i in range(totalExpect)]) 
dataOpen = decryption(dataCombine)

print("\n" + "="*15 + " 3. HASIL AKHIR " + "="*15)
if typeReceive == 1:
    print_hexdump(dataOpen, max_bytes=48, title="Hex Dump: Payload Teks Didekripsi")
    print(f"\nPesan Chat Masuk: \"{dataOpen.decode('utf-8')}\"")
elif typeReceive == 2:
    decompress_and_restore_image(dataOpen)