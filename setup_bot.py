import os

# Struktur folder yang kita butuhkan
DIRECTORIES = ["core", "lib", "config", "cogs", "data"]

def create_structure():
    print("🚀 Merapikan struktur Kotabi Bot...")
    for dir_path in DIRECTORIES:
        # Buat folder
        os.makedirs(dir_path, exist_ok=True)
        # Buat __init__.py agar folder dianggap package Python
        init_file = os.path.join(dir_path, "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, "w", encoding="utf-8") as f:
                f.write("")
        print(f"✔️ Folder {dir_path} sudah siap.")
    print("\n🎉 Semua folder berhasil dibuat!")

if __name__ == "__main__":
    create_structure()