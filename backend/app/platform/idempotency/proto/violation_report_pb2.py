"""Real Protobuf Python Message Definition for aner.idempotency.ViolationReport using google.protobuf."""

from __future__ import annotations

from typing import Any, cast

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

_file_proto = descriptor_pb2.FileDescriptorProto()
_file_proto.name = "violation_report.proto"
_file_proto.package = "aner.idempotency"

_msg_proto = _file_proto.message_type.add()
_msg_proto.name = "ViolationReportMessage"

_fields = [
    (
        "key_value",
        1,
        descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
        descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
    ),
    (
        "scope",
        2,
        descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
        descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
    ),
    (
        "operation_type",
        3,
        descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
        descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
    ),
    (
        "execution_count",
        4,
        descriptor_pb2.FieldDescriptorProto.TYPE_INT64,
        descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
    ),
    (
        "involved_object_ids",
        5,
        descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
        descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED,
    ),
    (
        "correlation_id",
        6,
        descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
        descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
    ),
]

for name, number, type_, label in _fields:
    f = _msg_proto.field.add()
    f.name = name
    f.number = number
    f.type = type_
    f.label = label

_pool = descriptor_pool.DescriptorPool()
_pool.Add(_file_proto)  # type: ignore[func-returns-value]
_file_desc = _pool.FindFileByName("violation_report.proto")
_PB2ViolationReport: Any = message_factory.GetMessageClass(
    _file_desc.message_types_by_name["ViolationReportMessage"]
)


class ViolationReport:
    """Wrapper around real google.protobuf Message for ViolationReport."""

    def __init__(
        self,
        key_value: str = "",
        scope: str = "",
        operation_type: str = "",
        execution_count: int = 0,
        involved_object_ids: list[str] | None = None,
        correlation_id: str = "",
    ) -> None:
        self._pb: Any = _PB2ViolationReport(
            key_value=key_value,
            scope=scope,
            operation_type=operation_type,
            execution_count=execution_count,
            correlation_id=correlation_id,
        )

        if involved_object_ids:
            self._pb.involved_object_ids.extend([str(x) for x in involved_object_ids])

    @property
    def key_value(self) -> str:
        return cast(str, getattr(self._pb, "key_value"))

    @key_value.setter
    def key_value(self, val: str) -> None:
        setattr(self._pb, "key_value", val)

    @property
    def scope(self) -> str:
        return cast(str, getattr(self._pb, "scope"))

    @scope.setter
    def scope(self, val: str) -> None:
        setattr(self._pb, "scope", val)

    @property
    def operation_type(self) -> str:
        return cast(str, getattr(self._pb, "operation_type"))

    @operation_type.setter
    def operation_type(self, val: str) -> None:
        setattr(self._pb, "operation_type", val)

    @property
    def execution_count(self) -> int:
        return cast(int, getattr(self._pb, "execution_count"))

    @execution_count.setter
    def execution_count(self, val: int) -> None:
        setattr(self._pb, "execution_count", val)

    @property
    def involved_object_ids(self) -> list[str]:
        return list(getattr(self._pb, "involved_object_ids"))

    @property
    def correlation_id(self) -> str:
        return cast(str, getattr(self._pb, "correlation_id"))

    @correlation_id.setter
    def correlation_id(self, val: str) -> None:
        setattr(self._pb, "correlation_id", val)

    def SerializeToString(self) -> bytes:  # noqa: N802
        """Serialize using real google.protobuf wire format."""
        return cast(bytes, self._pb.SerializeToString())

    def ParseFromString(self, data: bytes) -> ViolationReport:  # noqa: N802
        """Parse real google.protobuf binary payload."""
        pb = _PB2ViolationReport()
        pb.ParseFromString(data)
        self._pb = pb
        return self

    def to_dict(self) -> dict[str, Any]:
        """Return typed dictionary containing all 6 required fields."""
        return {
            "key_value": self.key_value,
            "scope": self.scope,
            "operation_type": self.operation_type,
            "execution_count": self.execution_count,
            "involved_object_ids": self.involved_object_ids,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ViolationReport:
        """Instantiate ViolationReport from a dictionary."""
        return cls(
            key_value=data.get("key_value", ""),
            scope=data.get("scope", ""),
            operation_type=data.get("operation_type", ""),
            execution_count=data.get("execution_count", 0),
            involved_object_ids=data.get("involved_object_ids", []),
            correlation_id=data.get("correlation_id", ""),
        )
