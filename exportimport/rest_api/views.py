from django.db import transaction
from rest_framework import permissions
from rest_framework import serializers
from rest_framework import status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FileUploadParser
from rest_framework.parsers import MultiPartParser
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from voteit.core.decorators import has_perm_drf
from voteit.core.rest_api import router
from voteit.meeting.models import Meeting
from voteit.meeting.permissions import MeetingPermissions
from voteit_tools.exportimport.exporter import Exporter
from voteit_tools.exportimport.importer import Importer
from voteit_tools.exportimport.rest_api.renderers import YAMLRenderer
from voteit_tools.exportimport.rest_api.serializers import ImportFileSerializer


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

    @has_perm_drf(MeetingPermissions.MODERATE)
    @action(
        methods=["GET"],
        detail=True,
        serializer_class=serializers.Serializer,
        renderer_classes=[JSONRenderer],
    )
    def json(self, request, *args, **kwargs):
        return self._run_export("json")

    @has_perm_drf(MeetingPermissions.MODERATE)
    @action(
        methods=["GET"],
        detail=True,
        serializer_class=serializers.Serializer,
        renderer_classes=[YAMLRenderer],
    )
    def yaml(self, request, *args, **kwargs):
        return self._run_export("yaml")

    def _run_export(self, file_suffix):
        instance = self.get_object()
        exporter = Exporter(instance)
        exporter()
        return Response(
            exporter.data.dict(exclude_none=True),
            headers={
                f"Content-Disposition": f'attachment; filename="meeting_{instance.pk}_export.{file_suffix}"'
            },
        )
