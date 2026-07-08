#!/usr/bin/env python3

"""

Audit imports in WelderBot project.



Checks every:

    from xxx import yyy



and verifies that yyy really exists inside module xxx.



Author: ChatGPT

"""



import ast

import importlib

import os

import sys



PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))



sys.path.insert(0, PROJECT_ROOT)



errors = []





def check_file(path):

    rel = os.path.relpath(path, PROJECT_ROOT)



    try:

        with open(path, "r", encoding="utf-8") as f:

            tree = ast.parse(f.read(), filename=rel)

    except Exception as e:

        errors.append(f"❌ Cannot parse {rel}: {e}")

        return



    for node in ast.walk(tree):



        if isinstance(node, ast.ImportFrom):



            module = node.module



            if module is None:

                continue



            try:

                mod = importlib.import_module(module)



            except Exception as e:

                errors.append(

                    f"\n❌ {rel}:{node.lineno}"

                    f"\n   Cannot import module '{module}'"

                    f"\n   {type(e).__name__}: {e}"

                )

                continue



            for alias in node.names:



                name = alias.name



                if name == "*":

                    continue



                if not hasattr(mod, name):



                    errors.append(

                        f"\n❌ {rel}:{node.lineno}"

                        f"\n   Missing: {name}"

                        f"\n   Module : {module}"

                    )





for root, dirs, files in os.walk(PROJECT_ROOT):



    if ".venv" in root:

        continue



    if "__pycache__" in root:

        continue



    for file in files:



        if file.endswith(".py"):



            check_file(os.path.join(root, file))





print("=" * 70)



if errors:



    print(f"Found {len(errors)} problem(s):")



    for e in errors:

        print(e)



else:



    print("✅ No broken imports found.")



print("=" * 70)
