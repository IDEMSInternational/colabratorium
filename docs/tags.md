Tags are a special type of form entity, they allow dynamic creation of subforms based on the `key_value` property of another table, for our purposes the tags table.
Each entry in the tags table is a tag group, and can be given a display name, and configure the corresponding subform with a JSON entry.
These JSON entries follow the same pattern as other entities. See these examples.

Behaviours of tags are still in beta. Currently they have fragile support for having multiple entries per tag group.

```json
{
  "time_spent": {
    "type": "decimal", 
    "label": "Time Spent"
  }
}
```

```json
{
  "work_area": {
    "type": "select_multiple", 
    "label": "Work Area",
    "appearance": "dropdown", 
    "list_name": "work_area_list", 
    "work_area_list":
      {
        "agroecology": "Agroecology",
        "saas": "SaaS",
        ...
      }
  }
}
```
