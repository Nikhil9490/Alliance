from notion_client import Client


class NotionDB:
    def __init__(self, token, database_id, id_prop):
        self.client = Client(auth=token)
        self.db_id = database_id
        self.id_prop = id_prop

    def find_by_id(self, hcp_id):
        res = self.client.databases.query(
            database_id=self.db_id,
            filter={"property": self.id_prop, "rich_text": {"equals": str(hcp_id)}},
        )
        results = res.get("results", [])
        return results[0] if results else None

    def query(self, filter=None):
        params = {"database_id": self.db_id}
        if filter:
            params["filter"] = filter
        results = []
        while True:
            res = self.client.databases.query(**params)
            results.extend(res.get("results", []))
            if not res.get("has_more"):
                break
            params["start_cursor"] = res["next_cursor"]
        return results

    def get_all_with_id(self):
        return self.query(filter={"property": self.id_prop, "rich_text": {"is_not_empty": True}})

    def get_all_without_id(self):
        return self.query(filter={"property": self.id_prop, "rich_text": {"is_empty": True}})

    def upsert(self, hcp_id, props):
        existing = self.find_by_id(hcp_id)
        if existing:
            self.client.pages.update(page_id=existing["id"], properties=props)
            return "updated", existing["id"]
        page = self.client.pages.create(
            parent={"database_id": self.db_id},
            properties=props,
        )
        return "created", page["id"]

    def set_id(self, page_id, hcp_id):
        self.client.pages.update(
            page_id=page_id,
            properties={self.id_prop: {"rich_text": [{"text": {"content": str(hcp_id)}}]}},
        )

    def archive_page(self, page_id):
        self.client.pages.update(page_id=page_id, archived=True)


class NotionJobsDB(NotionDB):
    def __init__(self, token, database_id):
        super().__init__(token, database_id, id_prop="Job ID")

    # keep old method names so sync.py doesn't break
    def find_by_hcp_id(self, hcp_id):
        return self.find_by_id(hcp_id)

    def get_all_pages_with_job_id(self):
        return self.get_all_with_id()
