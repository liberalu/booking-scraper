class ValidationPipeline:
    def process_item(self, item, spider):
        return item


class PostgresPipeline:
    def process_item(self, item, spider):
        return item
