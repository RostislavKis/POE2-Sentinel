"""Test entity reading functionality."""
import logging
import time

logging.basicConfig(level=logging.DEBUG)

from terrain_reader import TerrainReader, EntityCategory, Rarity

print("=" * 60)
print("POE2 Entity Reader Test")
print("=" * 60)
print("\nMake sure POE2 is running and you're in a zone with monsters.\n")

reader = TerrainReader("steam")

print("Connecting to game...")
if not reader.connect():
    print("ERROR: Could not connect to PathOfExileSteam.exe")
    print("Make sure the game is running and you have admin rights.")
    exit(1)

print(f"Connected! Base: 0x{reader.base_address:X}")

print("\nSearching for InGameState...")
igs = reader.find_ingame_state()
if igs:
    print(f"Found InGameState at: 0x{igs:X}")
else:
    print("Could not find InGameState")
    exit(1)

print("\nReading Area Instance...")
area = reader.get_area_instance()
if area:
    print(f"Found AreaInstance at: 0x{area:X}")
else:
    print("Could not find AreaInstance")
    exit(1)

print("\nReading entities manually...")
from terrain_reader import Poe2Offsets
import struct

# Read AwakeEntities std::map directly
awake_entities_addr = area + Poe2Offsets.AreaInstance.AWAKE_ENTITIES
print(f"AwakeEntities map at: 0x{awake_entities_addr:X}")

# Read head pointer and size
head = reader._read_ptr(awake_entities_addr)
size = reader._read_int(awake_entities_addr + 8)
print(f"  Head: 0x{head:X}" if head else "  Head: None")
print(f"  Size: {size}")

if head and size and size > 0:
    # Read root node (head->parent)
    root = reader._read_ptr(head + Poe2Offsets.StdMapNode.PARENT)
    print(f"  Root: 0x{root:X}" if root else "  Root: None")

    # BFS to find ALL entities and count types
    if root:
        visited = set()
        queue = [root]
        visuals = 0
        real_entities = []

        while queue and len(visited) < 500:
            node = queue.pop(0)
            if not node or node == head or node in visited:
                continue
            visited.add(node)

            node_data = reader._read_bytes(node, 48)
            if not node_data or len(node_data) < 48:
                continue

            is_nil = node_data[Poe2Offsets.StdMapNode.IS_NIL]
            if is_nil != 0:
                continue

            entity_id = struct.unpack_from('<I', node_data, Poe2Offsets.StdMapNode.KEY_ID)[0]
            entity_ptr = struct.unpack_from('<Q', node_data, Poe2Offsets.StdMapNode.VALUE_ENTITY_PTR)[0]
            left = struct.unpack_from('<Q', node_data, Poe2Offsets.StdMapNode.LEFT)[0]
            right = struct.unpack_from('<Q', node_data, Poe2Offsets.StdMapNode.RIGHT)[0]

            # Queue children
            if left and left != head:
                queue.append(left)
            if right and right != head:
                queue.append(right)

            if entity_id >= 0x40000000:
                visuals += 1
            else:
                # Read metadata
                details = reader._read_ptr(entity_ptr + Poe2Offsets.Entity.ENTITY_DETAILS_PTR) if entity_ptr else None
                metadata = ""
                if details:
                    metadata = reader._read_std_wstring(details + Poe2Offsets.EntityDetails.NAME)
                real_entities.append((entity_id, entity_ptr, metadata))

        print(f"\nTraversed {len(visited)} nodes:")
        print(f"  Visual/decoration entities (id >= 0x40000000): {visuals}")
        print(f"  Real entities (id < 0x40000000): {len(real_entities)}")

        if real_entities:
            print("\nReal entities found:")
            for eid, eptr, meta in real_entities[:15]:
                print(f"  ID {eid}: {meta[:60]}..." if meta else f"  ID {eid}: (no metadata)")

            # Try to resolve Render component for first real monster
            for eid, eptr, meta in real_entities:
                if "/Monsters/" in meta and "MonsterMods" not in meta:
                    print(f"\n--- Testing component resolution for monster ID {eid} ---")
                    print(f"Entity ptr: 0x{eptr:X}")

                    # Read details
                    details = reader._read_ptr(eptr + Poe2Offsets.Entity.ENTITY_DETAILS_PTR)
                    print(f"EntityDetails: 0x{details:X}" if details else "EntityDetails: None")

                    if details:
                        # Read ComponentLookUp
                        lookup = reader._read_ptr(details + Poe2Offsets.EntityDetails.COMPONENT_LOOKUP_PTR)
                        print(f"ComponentLookUp: 0x{lookup:X}" if lookup else "ComponentLookUp: None")

                        if lookup:
                            # Read bucket
                            bucket_begin = reader._read_ptr(lookup + Poe2Offsets.ComponentLookUp.NAME_AND_INDEX_BUCKET)
                            bucket_end = reader._read_ptr(lookup + Poe2Offsets.ComponentLookUp.NAME_AND_INDEX_BUCKET + 8)
                            print(f"Bucket: 0x{bucket_begin:X} - 0x{bucket_end:X}" if bucket_begin and bucket_end else "Bucket: None")

                            if bucket_begin and bucket_end and bucket_end > bucket_begin:
                                num_entries = (bucket_end - bucket_begin) // Poe2Offsets.ComponentLookUp.ENTRY_STRIDE
                                print(f"Bucket entries: {num_entries}")

                                # List first few component names
                                print("Component names in bucket:")
                                for i in range(min(num_entries, 10)):
                                    entry_addr = bucket_begin + i * Poe2Offsets.ComponentLookUp.ENTRY_STRIDE
                                    name_ptr = reader._read_ptr(entry_addr)
                                    if name_ptr:
                                        name = reader._read_std_wstring(name_ptr)
                                        index = reader._read_int(entry_addr + 8)
                                        print(f"  [{i}] '{name}' -> index {index}")

                                # Now try to resolve Render
                                render = reader._resolve_component(eptr, "Render")
                                print(f"\nResolved 'Render' component: 0x{render:X}" if render else "\nCouldn't resolve 'Render' component")
                    break
        else:
            print("\nNo real entities found! You might be in town/hideout.")
            print("Try going to an area with monsters.")

print("\nUsing get_entities method...")
for attempt in range(3):
    print(f"\n--- Attempt {attempt + 1} ---")
    try:
        entities = reader.get_entities()
        print(f"Found {len(entities)} entities")
        
        if entities:
            # Count by category
            by_category = {}
            for e in entities:
                cat = e.category.name
                by_category[cat] = by_category.get(cat, 0) + 1
            
            print("\nEntities by category:")
            for cat, count in sorted(by_category.items()):
                print(f"  {cat}: {count}")
            
            # Show first 10 entities
            print("\nFirst 10 entities:")
            for i, e in enumerate(entities[:10]):
                alive = "alive" if e.is_alive else "dead"
                friendly = "friendly" if e.is_friendly else "hostile"
                print(f"  {i+1}. {e.category.name} at ({e.grid_x:.1f}, {e.grid_y:.1f}) - {e.rarity.name} {alive} {friendly}")
                if e.metadata:
                    print(f"      Meta: {e.metadata[:60]}...")
            
            # Show monsters specifically
            monsters = [e for e in entities if e.category == EntityCategory.MONSTER]
            print(f"\nMonsters: {len(monsters)}")
            for m in monsters[:5]:
                print(f"  - {m.rarity.name} at ({m.grid_x:.1f}, {m.grid_y:.1f}) HP: {m.hp_cur}/{m.hp_max}")
        else:
            print("No entities found - checking if we're reading the right address...")
            
    except Exception as ex:
        import traceback
        print(f"Error: {ex}")
        traceback.print_exc()
    
    time.sleep(2)

reader.disconnect()
print("\nDone!")
