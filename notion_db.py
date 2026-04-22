from notion_client import Client


class NotionJobsDB:
    HCP_ID_PROP = "Job ID"

    def __init__(self, token, database_id):
        self.client = Client(auth=token)
        self.db_id = database_id

    def find_by_hcp_id(self, hcp_id):
        res = self.client.databases.query(
            database_id=self.db_id,
            filter={
                "property": self.HCP_ID_PROP,
                "rich_text": {"equals": str(hcp_id)},
            },
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

    def get_all_pages_with_job_id(self):
        return self.query(filter={"property": self.HCP_ID_PROP, "rich_text": {"is_not_empty": True}})

    def upsert(self, hcp_id, props):
        existing = self.find_by_hcp_id(hcp_id)
        if existing:
            self.client.pages.update(page_id=existing["id"], properties=props)
            return "updated", existing["id"]
        page = self.client.pages.create(
            parent={"database_id": self.db_id},
            properties=props,
        )
        return "created", page["id"]

    def set_hcp_id(self, page_id, hcp_id):
        self.client.pages.update(
            page_id=page_id,
            properties={
                self.HCP_ID_PROP: {"rich_text": [{"text": {"content": str(hcp_id)}}]},
            },
        )

    def archive_page(self, page_id):
        self.client.pages.update(page_id=page_id, archived=True)
