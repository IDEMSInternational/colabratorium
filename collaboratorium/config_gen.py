#!/usr/bin/env python3
"""
config_gen.py

Generate a YAML configuration file from a DBML schema for Collaboratorium.

Usage:
    python config_gen.py schema.dbml config.yaml

Notes:
- Uses pydbml (PyDBML) to parse schema.dbml.
- Detects foreign keys and many-to-many link tables (link tables identified by having 'link' in their name).
- Properly handles self-referential link tables (e.g., initiative <-> initiative).
- Produces a config YAML with 'tables', 'links', and 'forms' sections.
"""

from pathlib import Path
import sys
import yaml
from collections import defaultdict

# defensive import of pydbml
try:
    from pydbml import PyDBML
except Exception as e:
    PyDBML = None


# -----------------------
# Type mapping (editable)
# -----------------------
TYPE_MAP = {
    "int": {"type": "integer"},
    "integer": {"type": "integer"},
    "bigint": {"type": "integer"},
    "serial": {"type": "integer"},
    "float": {"type": "decimal"},
    "decimal": {"type": "decimal"},
    "double": {"type": "decimal"},
    "text": {"type": "text", "appearance": "multiline"},
    "string": {"type": "string"},
    "varchar": {"type": "string"},
    "char": {"type": "string"},
    "bool": {"type": "boolean"},
    "boolean": {"type": "boolean"},
    "timestamp": {"type": "datetime"},
    "datetime": {"type": "datetime"},
    "date": {"type": "date"},
    "json": {"type": "text", "appearance": "multiline"},
    "uuid": {"type": "string", "appearance": "uuid"},
    "unknown": {"type": "string"},
}


# -----------------------
# Helpers
# -----------------------
def safe_column_type_name(col):
    """
    Robust extraction of the column type name from a pydbml Column object.
    Handles: string types, Enum/objects with .name, or fallback to str().
    """
    if not hasattr(col, "type"):
        return "unknown"
    t = col.type
    if isinstance(t, str):
        return t.lower()
    # If it's an object (Enum or similar), try .name, else str()
    try:
        return t.name.lower()
    except Exception:
        return str(t).lower()


def map_column_type(col):
    """
    Map a DBML column to a form-friendly configuration using TYPE_MAP.
    Returns a copy so callers can mutate safely.
    """
    base_type = safe_column_type_name(col)
    return TYPE_MAP.get(base_type, TYPE_MAP["unknown"]).copy()


def safe_get_refs(table):
    """Return list of refs for a table; support pydbml variations."""
    if hasattr(table, "get_refs"):
        try:
            return list(table.get_refs())
        except Exception:
            return []
    if hasattr(table, "refs"):
        try:
            return list(table.refs)
        except Exception:
            return []
    return []


def _first_colname(colref):
    """Return first column name from a ref column descriptor (list or single object)."""
    if colref is None:
        return None
    if isinstance(colref, (list, tuple)) and len(colref) > 0:
        try:
            return colref[0].name
        except Exception:
            return str(colref[0])
    try:
        return colref.name
    except Exception:
        return str(colref)


def _col_belongs_to_table(ref, table, which="col1"):
    """
    Check whether the column(s) in ref.col1/col2 belong to 'table'.
    Used as a defensive heuristic.
    """
    try:
        cols = getattr(ref, which)
        if isinstance(cols, (list, tuple)):
            for c in cols:
                if getattr(c, "table", None) and getattr(c.table, "name", None) == table.name:
                    return True
        else:
            if getattr(cols, "table", None) and getattr(cols.table, "name", None) == table.name:
                return True
    except Exception:
        pass
    return False


def _try_colname_safe(ref, table_name):
    """
    Best-effort to return the link column name for link table side of the ref.
    """
    try:
        if getattr(ref.table1, "name", None) == table_name:
            return _first_colname(ref.col1)
        if getattr(ref.table2, "name", None) == table_name:
            return _first_colname(ref.col2)
    except Exception:
        pass
    return _first_colname(getattr(ref, "col1", None)) or _first_colname(getattr(ref, "col2", None))


# -----------------------
# Link-table discovery
# -----------------------
def discover_link_tables(db):
    """
    Find link tables (name contains 'link' AND at least two FK refs).
    Returns mapping:
      { link_table_name: { "table_obj": <pydbml.Table>, "mappings": [ {link_col, target_table, target_col}, ... ] } }
    """
    out = {}
    for table in db.tables:
        if "link" not in table.name.lower():
            continue

        refs = safe_get_refs(table)
        if len(refs) < 2:
            # not a full many-to-many link table; ignore or handle as partial
            continue

        mappings = []
        for ref in refs:
            try:
                if getattr(ref.table1, "name", None) == table.name:
                    link_col = _first_colname(ref.col1)
                    target_table = ref.table2.name
                    target_col = _first_colname(ref.col2)
                elif getattr(ref.table2, "name", None) == table.name:
                    link_col = _first_colname(ref.col2)
                    target_table = ref.table1.name
                    target_col = _first_colname(ref.col1)
                else:
                    # fallback detection
                    if _col_belongs_to_table(ref, table, which="col1"):
                        link_col = _first_colname(ref.col1)
                        target_table = ref.table2.name
                        target_col = _first_colname(ref.col2)
                    else:
                        link_col = _first_colname(ref.col2)
                        target_table = ref.table1.name
                        target_col = _first_colname(ref.col1)
            except Exception:
                link_col = _try_colname_safe(ref, table.name)
                target_table = getattr(ref.table2, "name", None) or getattr(ref.table1, "name", None)
                target_col = _first_colname(getattr(ref, "col2", None)) or _first_colname(getattr(ref, "col1", None))

            mappings.append({
                "link_col": link_col,
                "target_table": target_table,
                "target_col": target_col
            })

        out[table.name] = {"table_obj": table, "mappings": mappings}

    return out


# -----------------------
# Foreign-key collection
# -----------------------
def collect_foreign_keys(db):
    """
    Construct mapping:
      fk_map[table_name][local_col] = {"target_table": <>, "target_column": <>}
    For every reference declared on each table.
    """
    fk_map = defaultdict(dict)
    for table in db.tables:
        refs = safe_get_refs(table)
        for ref in refs:
            try:
                if getattr(ref.table1, "name", None) == table.name:
                    local_col = _first_colname(ref.col1)
                    target_table = ref.table2.name
                    target_col = _first_colname(ref.col2)
                elif getattr(ref.table2, "name", None) == table.name:
                    local_col = _first_colname(ref.col2)
                    target_table = ref.table1.name
                    target_col = _first_colname(ref.col1)
                else:
                    continue
            except Exception:
                continue
            if local_col:
                fk_map[table.name][local_col] = {"target_table": target_table, "target_column": target_col}
    return fk_map


# -----------------------
# Form element generation
# -----------------------
def guess_label_column_for_table(table_obj):
    """
    Pick a reasonable label column from a table object (prefer 'name', 'title', else first non-id).
    If table_obj is None, default to 'name'.
    """
    if table_obj is None:
        return "name"
    for preferred in ("name", "title", "label"):
        for c in table_obj.columns:
            if c.name.lower() == preferred:
                return c.name
    for c in table_obj.columns:
        if c.name.lower() not in ("id",):
            return c.name
    return "id"


def _heuristic_find_map_for_table(mappings, table_name):
    """Return the mapping whose link_col or target_table best matches table_name if mine mapping is missing."""
    for m in mappings:
        if m.get("link_col") and table_name in m.get("link_col"):
            return m
    return mappings[0]


def _guess_self_link_role(col_a, col_b):
    """
    crude heuristic for self-link role naming:
    if col_a contains 'parent' -> 'parents', if contains 'child' -> 'children'
    else if it contains 'from'/'to' or 'source'/'target', name accordingly
    """
    a = (col_a or "").lower()
    b = (col_b or "").lower()
    if "parent" in a:
        return "parents"
    if "child" in a:
        return "children"
    if "from" in a:
        return "from"
    if "to" in a:
        return "to"
    return None


def _label_for_self_link(role_name, table_name):
    if role_name == "parents":
        return "Parent " + table_name.replace("_", " ").title()
    if role_name == "children":
        return "Child " + table_name.replace("_", " ").title()
    return role_name.replace("_", " ").title()


def generate_elements_for_table(table, db, fk_map, links_info):
    """
    Build elements dict for a table:
     - normal columns -> mapped with map_column_type()
     - foreign keys -> select_one with parameters
     - many-to-many link selections -> select_multiple with store mapping, including self-links
    """
    elements = {}

    # 1) map normal & foreign-key columns
    for col in table.columns:
        if col.name in ("id", "version", "timestamp", "created_by", "updated_at"):
            continue

        fk = fk_map.get(table.name, {}).get(col.name)
        if fk:
            target_table_obj = next((t for t in db.tables if t.name == fk["target_table"]), None)
            label_col = guess_label_column_for_table(target_table_obj)
            elements[col.name] = {
                "type": "select_one",
                "appearance": "dropdown",
                "label": col.name.replace("_", " ").title(),
                "parameters": {
                    "source_table": fk["target_table"],
                    "value_column": fk.get("target_column") or "id",
                    "label_column": label_col
                }
            }
        else:
            mapped = map_column_type(col)
            mapped["label"] = col.name.replace("_", " ").title()
            elements[col.name] = mapped

    # 2) link-table based many-to-many elements
    for link_table_name, info in links_info.items():
        mappings = info.get("mappings", [])
        if not mappings:
            continue

        # find mappings that target current table and those that target others
        mine = [m for m in mappings if m.get("target_table") == table.name]
        others = [m for m in mappings if m.get("target_table") != table.name]

        if mine and others:
            # normal many-to-many linking this table to other table(s)
            mine_map = mine[0]
            for other in others:
                other_table_name = other.get("target_table")
                other_table_obj = next((t for t in db.tables if t.name == other_table_name), None)
                label_col = guess_label_column_for_table(other_table_obj)
                element_key = f"{other_table_name}_links"
                elements[element_key] = {
                    "type": "select_multiple",
                    "appearance": "dropdown",
                    "label": f"Linked {other_table_name.replace('_', ' ').title()}",
                    "parameters": {
                        "source_table": other_table_name,
                        "value_column": other.get("target_col") or "id",
                        "label_column": label_col
                    },
                    "store": {
                        "link_table": link_table_name,
                        "source_field": mine_map.get("link_col"),
                        "target_field": other.get("link_col"),
                        "orientation": "forward"
                    }
                }
        else:
            # possible self-referential link: all mappings target this table
            if len(mappings) >= 2 and all(m.get("target_table") == table.name for m in mappings):
                m1, m2 = mappings[0], mappings[1]
                role1 = _guess_self_link_role(m1["link_col"], m2["link_col"]) or "parents"
                role2 = _guess_self_link_role(m2["link_col"], m1["link_col"]) or "children"

                elements_key1 = f"{role1}"
                elements[elements_key1] = {
                    "type": "select_multiple",
                    "appearance": "dropdown",
                    "label": _label_for_self_link(role1, table.name),
                    "parameters": {
                        "source_table": table.name,
                        "value_column": m2.get("target_col") or "id",
                        "label_column": guess_label_column_for_table(table)
                    },
                    "store": {
                        "link_table": link_table_name,
                        "source_field": m1.get("link_col"),
                        "target_field": m2.get("link_col"),
                        "orientation": "self"
                    }
                }

                elements_key2 = f"{role2}"
                elements[elements_key2] = {
                    "type": "select_multiple",
                    "appearance": "dropdown",
                    "label": _label_for_self_link(role2, table.name),
                    "parameters": {
                        "source_table": table.name,
                        "value_column": m1.get("target_col") or "id",
                        "label_column": guess_label_column_for_table(table)
                    },
                    "store": {
                        "link_table": link_table_name,
                        "source_field": m2.get("link_col"),
                        "target_field": m1.get("link_col"),
                        "orientation": "self"
                    }
                }

    return elements


# -----------------------
# Top-level config builder
# -----------------------
def build_config(db):
    config = {"tables": {}, "links": {}, "forms": {}, "default_forms": {},}

    links_info = discover_link_tables(db)
    fk_map = collect_foreign_keys(db)

    # populate links section
    for link_table_name, info in links_info.items():
        config["links"][link_table_name] = {
            "mappings": [
                {"link_col": m["link_col"], "target_table": m["target_table"], "target_col": m["target_col"]}
                for m in info.get("mappings", [])
            ]
        }

    # build tables and forms
    for table in db.tables:
        fields = {}
        for col in table.columns:
            fields[col.name] = safe_column_type_name(col)
        config["tables"][table.name] = {"fields": fields}

        # table links (which link tables reference this table)
        table_links = {}
        for link_table_name, info in links_info.items():
            if any(m.get("target_table") == table.name for m in info.get("mappings", [])):
                table_links[link_table_name] = [
                    {"link_col": m["link_col"], "target_table": m["target_table"], "target_col": m["target_col"]}
                    for m in info.get("mappings", [])
                ]
        if table_links:
            config["tables"][table.name]["links"] = table_links

        form_name = f"{table.name}_form"
        config["default_forms"][table.name] = form_name
        elements = generate_elements_for_table(table, db, fk_map, links_info)
        meta = generate_meta_for_table(table)
        config["forms"][form_name] = {
            "label": table.name.replace("_", " ").title(),
            "default_table": table.name,
            "elements": elements,
            "meta": meta
        }

    return config


def generate_meta_for_table(table):
    """Define default meta strategies for usual meta columns."""
    meta = {}
    for col in table.columns:
        name = col.name.lower()
        if name == "id":
            meta[name] = {"strategy": "uuid", "editable": False}
        elif name == "version":
            meta[name] = {"strategy": "increment"}
        elif name in ("timestamp", "updated_at", "created_at"):
            meta[name] = {"strategy": "now"}
        elif name in ("created_by", "user_id"):
            meta[name] = {"strategy": "current_user"}
    return meta


# -----------------------
# Main
# -----------------------
def main(schema_path, output_path):
    if PyDBML is None:
        raise RuntimeError("pydbml is required to run this script. Install with `pip install pydbml`.")

    schema_path = Path(schema_path)
    if not schema_path.exists():
        raise FileNotFoundError(f"{schema_path} not found.")

    db = PyDBML(schema_path.read_text(encoding="utf-8"))

    config = build_config(db)

    out_path = Path(output_path)
    out_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    print(f"✅ Wrote config to {out_path.resolve()}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python config_gen.py schema.dbml config.yaml")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
