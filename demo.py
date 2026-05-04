import subprocess
import fakeredis
from user_manager import UserManager

subprocess.run('cls', shell=True)

client = fakeredis.FakeRedis(decode_responses=True)
mgr = UserManager(client=client)

# Add users
id1 = mgr.add_user("Alice", role="admin", email="alice@example.com")
id2 = mgr.add_user("Bob",   role="viewer")
id3 = mgr.add_user("Carol")
id4 = mgr.add_user("Pankaj")
print(f"Created: {id1}, {id2}, {id3}, {id4}")
print()

# Fetch by ID
print("Get by ID:", mgr.get_user_by_id(id4))
print()

# List all
print("All users:")
for u in mgr.get_all_users():
    print(" ", u)
print()

# Duplicate name raises
try:
    mgr.add_user("Alice")
except Exception as e:
    print(f"Duplicate blocked: {e}")
