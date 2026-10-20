"""JSON values whose exact floating-point representation is part of the contract."""
from django.db import models


class LosslessJSONField(models.JSONField):
    """Keep JSON text intact on MySQL, including signed raw-event coordinates."""

    def db_type(self, connection):
        if connection.vendor == 'mysql':
            return 'longtext'
        return super().db_type(connection)

    def db_check(self, connection):
        if connection.vendor == 'mysql':
            return 'JSON_VALID(%s)' % connection.ops.quote_name(self.column)
        return super().db_check(connection)
