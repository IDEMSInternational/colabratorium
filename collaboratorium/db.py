import sqlite3
import os
from datetime import datetime, timezone
import json
import pandas as pd
from pydbml import PyDBML
import networkx as nx  # Import networkx for degree filtering
from visual_customization import NODE_TABLES


DB = 'database.db'
DBML_FILE = 'schema.dbml'

# Load the DBML schema once at the module level
try:
    with open(DBML_FILE) as f:
        dbml = PyDBML(f)
except FileNotFoundError:
    print(f"[ERROR] DBML file not found at {DBML_FILE}. Functions in db.py will fail.")
    dbml = None
except Exception as e:
    print(f"[ERROR] Failed to parse DBML file {DBML_FILE}: {e}")
    dbml = None


def db_connect():
    """Returns a new connection to the SQLite database."""
    return sqlite3.connect(DB)


def _now_utc_iso():
    """Returns the current time in UTC ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _dbml_to_sqlite_type(col_type: str) -> str:
    """Helper to map DBML data types to SQLite data types."""
    t = col_type.lower()
    if t in ('int', 'integer'):
        return 'INTEGER'
    if t == 'boolean':
        return 'INTEGER'  # SQLite uses 0/1 for booleans
    if t in ('datetime', 'date', 'timestamp'):
        return 'TEXT'
    # Default for varchar, text, char, string, etc.
    return 'TEXT'


def init_db():
    """
    Create the database schema dynamically from the DBML file.
    Optionally seeds default data.
    """
    existed = os.path.exists(DB)
    
    if existed:
        print("Database already exists. Skipping initialization.")
        return

    if dbml is None:
        raise RuntimeError(f"DBML file not found or failed to parse at {DBML_FILE}. Cannot initialize DB.")

    conn = db_connect()
    cur = conn.cursor()

    print("Initializing database schema from DBML...")
    # Dynamically create tables from DBML
    for table in dbml.tables:
        col_defs = []
        has_id = False
        has_version = False
        
        for col in table.columns:
            # Use quotes to handle all table/column names
            col_defs.append(f'"{col.name}" {_dbml_to_sqlite_type(col.type)}')
            if col.name == 'id':
                has_id = True
            if col.name == 'version':
                has_version = True
        
        # Add composite primary key for versioned tables
        # Assumes tables with 'id' and 'version' are versioned
        if has_id and has_version:
            col_defs.append("PRIMARY KEY (id, version)")
        
        sql = f'CREATE TABLE IF NOT EXISTS "{table.name}" ({", ".join(col_defs)})'
        try:
            cur.execute(sql)
        except Exception as e:
            print(f"Failed to create table {table.name}: {e}\nSQL: {sql}")

    conn.commit()
    print("Database schema initialized.")

    # Seed data if the DB was just created
    if not existed:
        print("Seeding database...")
        try:
            # Seed data (same as your original file)
            now = _now_utc_iso()
            cur.execute('INSERT INTO people (id, version, name, role, email, active, timestamp, tags, status, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (1, 1, 'Alice', 'Data Scientist', 'alice@example.com', 1, now, json.dumps(['datascience']), 'active', 1))
            cur.execute('INSERT INTO people (id, version, name, role, email, active, timestamp, tags, status, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (2, 1, 'Bob', 'Project Manager', 'bob@example.com', 1, now, json.dumps(['pm']), 'active', 1))

            cur.execute('INSERT INTO organisations (id, version, timestamp, name, description, location, contact_person, tags, status, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (1, 1, now, 'Data Org', 'Org for data work', 'Remote', 1, json.dumps(['research']), 'active', 1))

            cur.execute('INSERT INTO initiatives (id, version, name, description, responsible_person, timestamp, tags, status, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (1, 1, 'Project Phoenix', 'Rebuild the data pipeline', 2, now, json.dumps(['infra']), 'active', 1))

            cur.execute('INSERT INTO activities (id, version, timestamp, name, description, location, start_date, end_date, tags, status, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (1, 1, now, 'Q1 Research', 'Research for Phoenix', 'Remote', '2025-01-15', '2025-03-31', json.dumps(['research']), 'active', 1))

            cur.execute('INSERT INTO contracts (id, version, timestamp, name, description, organisation, organisation_person, responsible_person, start_date, end_date, tags, status, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (1, 1, now, 'Phoenix Contract', 'Contract for Phoenix work', 1, 1, 2, '2025-01-01', '2025-12-31', json.dumps(['contract']), 'active', 1))

            # links
            cur.execute('INSERT INTO organisation_people_links (id, version, timestamp, status, organisation_id, person_id, type, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (1, 1, now, 'active', 1, 1, 'member', 1))
            cur.execute('INSERT INTO activity_people_links (id, version, timestamp, status, activity_id, person_id, type, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (1, 1, now, 'active', 1, 1, 'reporter', 1))
            cur.execute('INSERT INTO activity_initiative_links (id, version, timestamp, status, activity_id, initiative_id, type, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (1, 1, now, 'active', 1, 1, 'part of', 1))
            cur.execute('INSERT INTO initiative_initiative_links (id, version, timestamp, status, parent_id, child_id, type, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (1, 1, now, 'active', 1, 1, 'parent', 1))
            cur.execute('INSERT INTO activity_contract_links (id, version, timestamp, status, activity_id, contract_id, type, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (1, 1, now, 'active', 1, 1, 'covered by', 1))
            cur.execute('INSERT INTO contract_initiative_links (id, version, timestamp, status, contract_id, initiative_id, type, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (1, 1, now, 'active', 1, 1, 'related to', 1))

            conn.commit()
            print("Database seeded.")
        except Exception as e:
            print(f"Error seeding database: {e}")
            conn.rollback()
    
    conn.close()


def build_elements_from_db(include_deleted: bool = False, node_types: list | None = None, people_selected: list | None = None, degree: int = None):
    """
    Build Cytoscape-style elements (nodes + edges) dynamically from the DBML schema.
    
    - include_deleted: Show items with 'deleted' status.
    - node_types: List of table names to show (e.g., ['people', 'initiatives']).
    - people_selected: List of people IDs (e.g., ['people-1']) to use as starting points.
    - degree: N-degree filtering from 'people_selected'. If None, shows all.
    """
    if dbml is None:
        raise RuntimeError(f"DBML file not found or failed to parse. Cannot build elements.")

    rconn = db_connect()

    def db_df(query):
        """Execute query, get latest version of each object, return DataFrame."""
        try:
            df = pd.read_sql_query(query, rconn)
        except Exception as e:
            print(f"[WARN] db_df query failed: {e}")
            return pd.DataFrame()
        if df.empty:
            return df
        # Get the latest version for each 'id'
        if 'id' in df.columns and 'version' in df.columns:
            df = df.sort_values(['id', 'version']).groupby('id', as_index=False).last()
        return df

    # Build the FK map first for easy lookup
    fk_map = {}  # (child_table, child_col) -> (parent_table, parent_col)
    try:
        for ref in dbml.refs:
            col1 = ref.col1[0]
            col2 = ref.col2[0]
            child = (col1.table.name, col1.name)
            parent = (col2.table.name, col2.name)
            fk_map[child] = parent
    except Exception as e:
        print(f"[WARN] Could not build FK map: {e}")

    # Load ALL tables into dataframes. Filtering happens in memory.
    dataframes = {}
    for table in dbml.tables:
        dataframes[table.name] = db_df(f'SELECT * FROM "{table.name}"')

    # Apply status filter (exclude deleted) if requested
    def _filter_deleted(df):
        if df is None or df.empty:
            return df
        if include_deleted:
            return df
        if 'status' in df.columns:
            return df[df['status'].isna() | (df['status'] != 'deleted')]
        return df

    for name, df in dataframes.items():
        dataframes[name] = _filter_deleted(df)

    # --- 1. Build ALL Nodes ---
    
    def make_node(row, table_name):
        """Helper to create a Cytoscape node element."""
        nid = f"{table_name}-{int(row['id'])}"
        label = row.get('name') or row.get('Name') or row.get('email') or f"{table_name} {row.get('id')}"
        props = {k: v for k, v in row.items()}
        return {'data': {'id': nid, 'label': label, 'type': table_name, 'properties': props}, 'classes': table_name}

    all_nodes = []
    for table_name in NODE_TABLES:
        df = dataframes.get(table_name)
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                try:
                    all_nodes.append(make_node(r, table_name))
                except Exception as e:
                    print(f"[WARN] Failed to create node for {table_name} row {r.get('id')}: {e}")
    
    # Set of all node IDs that were successfully created
    existing_node_ids = {n['data']['id'] for n in all_nodes}

    # --- 2. Build ALL Edges ---

    def add_edge(src_table, src_obj_id, tgt_table, tgt_obj_id, label, link_table=None, link_obj_id=None, link_status=None):
        """Helper to create a Cytoscape edge element."""
        try:
            if link_status == "deleted": return None
            if pd.isna(src_obj_id) or pd.isna(tgt_obj_id): return None
            
            src_id = f"{src_table}-{int(src_obj_id)}"
            tgt_id = f"{tgt_table}-{int(tgt_obj_id)}"
            
            # Don't add edges if the source/target node doesn't exist
            if src_id not in existing_node_ids or tgt_id not in existing_node_ids:
                return None
                
            # Create a unique edge ID
            if link_table and link_obj_id is not None:
                edge_id = f"{link_table}-{int(link_obj_id)}"
            else:
                # Implied FK edge
                edge_id = f"fk-{src_id}-{tgt_id}"

            data = {
                'id': edge_id,
                'source': src_id,
                'target': tgt_id,
                'label': label,
                'status': link_status
            }
            
            # If this is an editable edge (from a link table), add its info
            if link_table and link_obj_id is not None:
                data['table_name'] = link_table
                data['object_id'] = int(link_obj_id)

            return {'data': data}
        except Exception as e:
            print(f"[WARN] Failed to add edge {label} ({src_obj_id} -> {tgt_obj_id}): {e}")
            return None

    all_edges = []
    link_tables = [t for t in dbml.tables if t.name not in NODE_TABLES]
    
    for ref in dbml.refs:
        try:
            child_table = ref.col1[0].table
            child_col_name = ref.col1[0].name
            parent_table = ref.col2[0].table
            parent_col_name = ref.col2[0].name # Usually 'id'

            # Case 1: Direct FK (e.g., initiatives.responsible_person -> people.id)
            if child_table.name in NODE_TABLES:
                df = dataframes.get(child_table.name)
                if df is None or df.empty: continue
                for _, row in df.iterrows():
                    if row.get(child_col_name) is not None and not pd.isna(row.get(child_col_name)):
                        edge = add_edge(
                            src_table=parent_table.name, # 'people'
                            src_obj_id=row[child_col_name],
                            tgt_table=child_table.name, # 'initiatives'
                            tgt_obj_id=row[parent_col_name], # 'id'
                            label=child_col_name.replace('_', ' ').replace('id', ''),
                            link_status=row.get('status')
                        )
                        if edge: all_edges.append(edge)
            
            # Case 2: Link Table (e.g., organisation_people_links)
            elif child_table in link_tables:
                # Find the *other* FK on this link table
                other_fk_col = None
                for col in child_table.columns:
                    if col.name != child_col_name and (child_table.name, col.name) in fk_map:
                        other_fk_col = col
                        break
                
                if not other_fk_col: continue
                if child_col_name > other_fk_col.name: continue # Process each link table only once

                other_parent_table_name = fk_map[(child_table.name, other_fk_col.name)][0]
                
                # Handle self-referencing tables
                if child_table.name == 'initiative_initiative_links':
                    source_col_name, target_col_name = 'parent_id', 'child_id'
                    source_table_name, target_table_name = 'initiatives', 'initiatives'
                else:
                    source_col_name, target_col_name = other_fk_col.name, child_col_name
                    source_table_name, target_table_name = other_parent_table_name, parent_table.name

                df = dataframes.get(child_table.name)
                if df is None or df.empty: continue
                
                for _, row in df.iterrows():
                    edge = add_edge(
                        src_table=source_table_name,
                        src_obj_id=row[source_col_name],
                        tgt_table=target_table_name,
                        tgt_obj_id=row[target_col_name],
                        label=row.get('type') or child_table.name.replace('_links', '').replace('_', ' '),
                        link_table=child_table.name,
                        link_obj_id=row.get('id'),
                        link_status=row.get('status')
                    )
                    if edge: all_edges.append(edge)
        except Exception as e:
            print(f"[WARN] Failed to build edge from ref {ref.col1[0].table.name}.{ref.col1[0].name}: {e}")

    rconn.close()
    
    all_elements = all_nodes + all_edges

    # --- 3. Apply Degree Filter (if provided) ---
    
    final_elements = all_elements
    
    if people_selected and degree is not None:
        G = nx.Graph()
        for node in all_nodes:
            G.add_node(node['data']['id'])
        for edge in all_edges:
            G.add_edge(edge['data']['source'], edge['data']['target'])

        nodes_to_keep = set()
        start_nodes = [pid for pid in people_selected if G.has_node(pid)]

        for start_node in start_nodes:
            # ego_graph finds all nodes within 'radius' (degree)
            neighbors_graph = nx.ego_graph(G, start_node, radius=degree)
            nodes_to_keep.update(neighbors_graph.nodes())
        
        # Filter the elements based on the graph traversal
        nodes = [n for n in all_nodes if n['data']['id'] in nodes_to_keep]
        node_ids = {n['data']['id'] for n in nodes}
        edges = [e for e in all_edges if e['data']['source'] in node_ids and e['data']['target'] in node_ids]
        final_elements = nodes + edges

    # --- 4. Apply Node Type Filter (final step) ---
    
    if node_types:
        nodes = [e for e in final_elements if 'source' not in e['data'] and e['data']['type'] in node_types]
        node_ids = {n['data']['id'] for n in nodes}
        edges = [e for e in final_elements if 'source' in e['data'] and e['data']['source'] in node_ids and e['data']['target'] in node_ids]
        return nodes + edges
    else:
        # Return all elements (either degree-filtered or complete)
        return final_elements


# --- Utility Functions (unchanged) ---

def get_max_object_id(table_name: str):
    """Return the maximum object id (id column) for a table, or 0 if none."""
    conn = db_connect()
    cur = conn.cursor()
    try:
        cur.execute(f'SELECT MAX(id) FROM "{table_name}"')
        r = cur.fetchone()
        return int(r[0]) if r and r[0] is not None else 0
    finally:
        conn.close()


def get_max_version(table_name: str, object_id: int):
    conn = db_connect()
    cur = conn.cursor()
    try:
        cur.execute(f'SELECT MAX(version) FROM "{table_name}" WHERE id = ?', (object_id,))
        r = cur.fetchone()
        return int(r[0]) if r and r[0] is not None else 0
    finally:
        conn.close()