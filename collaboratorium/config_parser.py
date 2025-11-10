import yaml


class Config(dict):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fk_map = self.build_reference_index()

    def build_reference_index(self):
        """Build mappings of foreign key relationships."""
        fk_map = {}  # (child_table, child_column) -> (parent_table, parent_column)
        for link, link_dict in self["links"].items():
            for mapping in link_dict["mappings"]:
                child = (link, mapping["link_col"])
                parent = (mapping["target_table"], mapping["target_col"])
                fk_map[child] = parent
        return fk_map

def load_config(filepath):
    with open(filepath, "r") as f:
        config = Config(yaml.safe_load(f))
    
    return config

