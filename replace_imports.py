import os
import glob

def replace_in_file(filepath, old_text, new_text):
    with open(filepath, 'r', encoding='utf-8') as file:
        content = file.read()
    
    if old_text in content:
        content = content.replace(old_text, new_text)
        with open(filepath, 'w', encoding='utf-8') as file:
            file.write(content)
        print(f"Updated: {filepath}")
    else:
        print(f"No changes needed: {filepath}")

# Find all Python files in the current directory and subdirectories
print("Searching for files with 'from rapidfuzz'...")
for filepath in glob.glob('**/*.py', recursive=True):
    replace_in_file(filepath, 'from rapidfuzz', 'from rapidfuzz')

print("\nDone!")