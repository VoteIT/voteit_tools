from django.db import transaction
from pydantic import ValidationError as PydanticValidationError
from rest_framework import permissions
from rest_framework import status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FileUploadParser
from rest_framework.parsers import JSONParser
from rest_framework.parsers import MultiPartParser
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from voteit.core.decorators import has_perm_drf
from voteit.core.rest_api import router
from voteit.core.rest_api.utils import pydantic_to_drf_validation_error
from voteit.meeting.models import Meeting
from voteit.meeting.permissions import MeetingPermissions
from voteit_tools.exportimport.exporter import Exporter
from voteit_tools.exportimport.importer import Importer
from voteit_tools.exportimport.rest_api.renderers import YAMLRenderer
from voteit_tools.exportimport.rest_api.serializers import ImportFileSerializer
from voteit_tools.exportimport.rest_api.serializers import ExportFileSerializer


@router.register("meeting-data", basename="meeting-data")
class MeetingDataViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = Meeting.objects.all()
    serializer_class = ImportFileSerializer
    parser_classes = (MultiPartParser, FileUploadParser)

    def list(self, request, *args, **kwargs):
        return Response(data=[])

    @has_perm_drf(MeetingPermissions.CHANGE)
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(
            data=request.data,
            context={"meeting": instance, "request": request},
        )
        serializer.is_valid(raise_exception=True)
        # Dispatch job?
        importer = Importer(instance)
        importer.from_stream(request.data["file"])
        commit = serializer.data.get("commit")
        if commit:
            with transaction.atomic(durable=True):
                importer.run()
        return Response(
            data=importer.stats().dict(),
            status=commit and status.HTTP_201_CREATED or status.HTTP_200_OK,
        )

    @action(
        methods=["POST"],
        detail=True,
        renderer_classes=[JSONRenderer],
        parser_classes=[JSONParser],
    )
    @has_perm_drf(MeetingPermissions.MODERATE)
    def json(self, request, *args, **kwargs):
        return self._run_export(request, "json")

    @action(
        methods=["POST"],
        detail=True,
        renderer_classes=[YAMLRenderer],
    )
    @has_perm_drf(MeetingPermissions.MODERATE)
    def yaml(self, request, *args, **kwargs):
        return self._run_export(request, "yaml")

    def _run_export(self, request, file_suffix):
        instance = self.get_object()
        serializer = ExportFileSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)
        exporter = Exporter(instance, **serializer.data)
        try:
            exporter()
        except PydanticValidationError as exc:
            raise pydantic_to_drf_validation_error(exc)
        return Response(
            exporter.data.dict(exclude_none=True),
            headers={
                f"Content-Disposition": f'attachment; filename="meeting_{instance.pk}_export.{file_suffix}"'
            },
        )
