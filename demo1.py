# =============================================================================
# Redis User Manager — demo1.py
# Run from VS Code terminal: .venv\Scripts\python.exe demo1.py <command>
#
# TEST 1: No arguments — shows help
#   .venv\Scripts\python.exe demo1.py
#
# TEST 2: Full demo — add, get, list in one run
#   .venv\Scripts\python.exe demo1.py demo
#
# TEST 3: List seeded users
#   .venv\Scripts\python.exe demo1.py list
#
# TEST 4: Add single user with role and email
#   .venv\Scripts\python.exe demo1.py add "Carol" --role manager --email carol@example.com
#
# TEST 5: Add multiple users at once
#   .venv\Scripts\python.exe demo1.py add "Dave" "Eve" --role viewer
#
# TEST 6: Get user by ID (copy ID from [Seeded] line after running list)
#   .venv\Scripts\python.exe demo1.py list
#   .venv\Scripts\python.exe demo1.py get PA12345
#
# TEST 7: Get with invalid ID — shows friendly error
#   .venv\Scripts\python.exe demo1.py get INVALID123
#
# TEST 8: Duplicate user — should be blocked
#   .venv\Scripts\python.exe demo1.py add "Pankaj"
# =============================================================================

import subprocess
import argparse
import fakeredis
from user_manager import UserManager

subprocess.run('cls', shell=True)

parser = argparse.ArgumentParser(description="Redis User Manager CLI")
subparsers = parser.add_subparsers(dest="command")

# add command
add_parser = subparsers.add_parser("add", help="Add a new user")
add_parser.add_argument("names", nargs="+", help="One or more user names to add")
add_parser.add_argument("--role",  help="Role for all users")
add_parser.add_argument("--email", help="Email (only used when adding a single user)")

# get command
get_parser = subparsers.add_parser("get", help="Get user by ID")
get_parser.add_argument("user_id", help="User ID to look up")

# list command
subparsers.add_parser("list", help="List all users")

# demo command
subparsers.add_parser("demo", help="Add sample users and list all")

args = parser.parse_args()

client = fakeredis.FakeRedis(decode_responses=True)
mgr = UserManager(client=client)

# Seed users for all commands except demo (demo seeds its own)
if args.command != "demo":
    _id_pankaj = mgr.add_user("Pankaj", role="admin", email="pankaj@example.com")
    _id_alice  = mgr.add_user("Alice",  role="viewer")
    _id_bob    = mgr.add_user("Bob")
    print(f"[Seeded] Pankaj={_id_pankaj}  Alice={_id_alice}  Bob={_id_bob}\n")

if args.command == "add":
    for name in args.names:
        extras = {k: v for k, v in [("role", args.role), ("email", args.email)] if v}
        user_id = mgr.add_user(name, **extras)
        print(f"Created — ID: {user_id}, Name: {name}")

elif args.command == "get":
    try:
        user = mgr.get_user_by_id(args.user_id)
        print("User found:", user)
    except Exception as e:
        print(f"Error: {e}")
        print("Tip: Use the ID shown in [Seeded] line above.")

elif args.command == "list":
    users = mgr.get_all_users()
    for u in users:
        print(u)

elif args.command == "demo":
    id1 = mgr.add_user("Pankaj", role="admin", email="pankaj@example.com")
    id2 = mgr.add_user("Alice",  role="viewer")
    id3 = mgr.add_user("Bob")
    print(f"Created: {id1}, {id2}, {id3}\n")
    print("Get by ID:", mgr.get_user_by_id(id1), "\n")
    print("All users:")
    for u in mgr.get_all_users():
        print(" ", u)

else:
    parser.print_help()
