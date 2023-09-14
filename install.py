import sus
import os

req_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "requirements.txt")

with open(req_file) as file:
    for lib in file:
        lib = lib.strip()
        if not sus.is_installed(lib):
            sus.run_pip(f"install {lib}", f"Deforum requirement: {lib}")
