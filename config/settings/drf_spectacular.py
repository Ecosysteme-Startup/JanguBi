SPECTACULAR_SETTINGS = {
    'TITLE': 'JanguBi API',
    'DESCRIPTION': 'API for JanguBi',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    # Noms stables des énumérations de la V1 (sinon drf-spectacular suffixe au hasard
    # les collisions « status », « kind »… et le client généré change à chaque lot).
    'ENUM_NAME_OVERRIDES': {
        'NodeStatusEnum': 'apps.hierarchy.enums.NodeStatus',
        'PlaceKindEnum': 'apps.hierarchy.enums.PlaceKind',
        'ScheduleKindEnum': 'apps.hierarchy.enums.ScheduleKind',
        'WeekdayEnum': 'apps.hierarchy.enums.Weekday',
        'AssignmentStatusEnum': 'apps.hierarchy.enums.AssignmentStatus',
        'EtatDeVieEnum': 'apps.hierarchy.enums.EtatDeVie',
        'DegreOrdreEnum': 'apps.hierarchy.enums.DegreOrdre',
        'RequiredOrderEnum': 'apps.hierarchy.enums.RequiredOrder',
        'CardinalityEnum': 'apps.hierarchy.enums.Cardinality',
        'ArticleStatusEnum': 'apps.news.models.Article.Status',
        'ArticleContentTypeEnum': 'apps.news.models.Article.ContentType',
        'ArticleV1TypeEnum': 'apps.news.serializers.V1_TYPES',
        'DocumentRequestStatusEnum': 'apps.documents.models.DocumentRequest.Status',
        'DocumentRequestV1StatusEnum': 'apps.documents.serializers.V1_STATUS_CHOICES',
        'PickupModeEnum': 'apps.documents.models.DocumentRequest.PickupMode',
        'EventTypeEnum': 'apps.agenda.models.Event.EventType',
    },
}
