import os
import zipfile
import hashlib

DIST_DIR = r"C:\Users\soren\.gemini\antigravity\scratch\phnoe-web-app\examples\soren-motion-v8\dist"
OUT_DIR = r"C:\Users\soren\.gemini\antigravity\scratch\phnoe-web-app\artifacts"
BRAIN_DIR = r"C:\Users\soren\.gemini\antigravity\brain\495c71cb-e3c9-445b-aa12-946a7641450f"

zip_name = "SOREN-Section-Explorers-v8-Cybernetic.zip"
sha_name = "SOREN-Section-Explorers-v8-Cybernetic.sha256"

zip_path = os.path.join(OUT_DIR, zip_name)
sha_path = os.path.join(OUT_DIR, sha_name)
brain_zip_path = os.path.join(BRAIN_DIR, zip_name)
brain_sha_path = os.path.join(BRAIN_DIR, sha_name)

print("Creating portable ZIP archive from dist/...")
file_count = 0
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(DIST_DIR):
        for f in files:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, DIST_DIR)
            zf.write(full_path, arcname=rel_path)
            file_count += 1

print(f"Packaged {file_count} files into {zip_path}")

# Compute SHA-256
hasher = hashlib.sha256()
with open(zip_path, 'rb') as f:
    while chunk := f.read(65536):
        hasher.update(chunk)
digest = hasher.hexdigest()

sha_content = f"{digest}  {zip_name}\n"
with open(sha_path, 'w', encoding='utf-8') as f:
    f.write(sha_content)

# Mirror to brain directory
import shutil
shutil.copyfile(zip_path, brain_zip_path)
shutil.copyfile(sha_path, brain_sha_path)

print(f"SHA-256: {digest}")
print(f"Saved manifest to {sha_path} and {brain_sha_path}")
