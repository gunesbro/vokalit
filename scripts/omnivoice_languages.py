"""Throwaway: finds the language tables inside the installed omnivoice package (without importing it) and prints
them as JSON. Run from the repo root with OmniVoice installed:

    .\\.local\\omnivoice\\venv\\Scripts\\python.exe scripts\\omnivoice_languages.py

It writes omnivoice-languages.json (UTF-8) in the current folder.
"""
import ast
import json
import os
import sys
import sysconfig

package = os.path.join(sysconfig.get_paths()["purelib"], "omnivoice")
if not os.path.isdir(package):
    sys.exit(f"omnivoice is not installed in this Python ({sys.executable}).")

found = []
for folder, _, files in os.walk(package):
    for file in files:
        if not file.endswith(".py"):
            continue
        path = os.path.join(folder, file)
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.List, ast.Tuple, ast.Dict, ast.Set)):
                size = len(node.keys) if isinstance(node, ast.Dict) else len(node.elts)
                if size < 100:
                    continue
                try:
                    value = ast.literal_eval(node)
                except ValueError:
                    continue
                found.append({"file": os.path.relpath(path, package), "line": node.lineno, "size": size,
                              "value": value if not isinstance(value, set) else sorted(value)})

# Language data files shipped with the package, if any.
data_files = [os.path.relpath(os.path.join(folder, f), package) for folder, _, files in os.walk(package)
              for f in files if f.endswith((".json", ".tsv", ".csv", ".txt", ".md"))]
# Written as UTF-8 by the script itself: the Windows console's code page cannot print every language name.
with open("omnivoice-languages.json", "w", encoding="utf-8") as f:
    json.dump({"tables": found, "data_files": data_files}, f, ensure_ascii=False, indent=1)
print(f"Wrote omnivoice-languages.json ({len(found)} tables).")
