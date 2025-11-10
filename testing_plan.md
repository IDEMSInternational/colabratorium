
## System tests 
### DBML -> config_gen -> config -> interpretation
Compare build_reference_index to
```python
fk_map = {}  # (child_table, child_column) -> (parent_table, parent_column)
for ref in dbml.refs:
    col1 = ref.col1[0]
    col2 = ref.col2[0]
    child = (col1.table.name, col1.name)
    parent = (col2.table.name, col2.name)
    fk_map[child] = parent
return fk_map
```
with

```python
value_differences = {}
for key in set(dict_a.keys()) & set(dict_b.keys()):
    if dict_a[key] != dict_b[key]:
        value_differences[key] = (dict_a[key], dict_b[key])

print(f"Value differences for common keys: {value_differences}")
print(f"Keys are the same: {(set(dict_a.keys()) & set(dict_b.keys())) == set(dict_b.keys())}")
```
Though sometimes we want different links, e.g. we don't care to show links for created_by 

Compare init_db sql queries to
```python
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
```