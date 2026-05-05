import subprocess
import argparse
import fakeredis
from user_manager import UserManager

subprocess.run('cls', shell=True)

client = fakeredis.FakeRedis(decode_responses=True)
mgr = UserManager(client=client)

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

# demo command — adds sample users and lists them
subparsers.add_parser("demo", help="Add sample users and list all")

args = parser.parse_args()

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
        print("Note: fakeredis is in-memory. Use 'demo' command to add and get in one run.")

elif args.command == "list":
    users = mgr.get_all_users()
    if users:
        for u in users:
            print(u)
    else:
        print("No users found.")

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
