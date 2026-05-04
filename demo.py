import fakeredis
from user_manager import UserManager

client = fakeredis.FakeRedis(decode_responses=True)
mgr = UserManager(client=client)

# Add users
id1 = mgr.add_user("Alice", role="admin", email="alice@example.com")
id2 = mgr.add_user("Bob",   role="viewer")
id3 = mgr.add_user("Carol")

print(f"Created: {id1}, {id2}, {id3}")
print()

# Fetch by ID
print("Get by ID:", mgr.get_user_by_id(id1))
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
