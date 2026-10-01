from django.urls import path

from apps.donations import apis, apis_compteurs

urlpatterns = [
    path("fonds/", apis.FundListCreateApi.as_view(), name="funds"),
    path("fonds/<uuid:fund_id>/", apis.FundDetailApi.as_view(), name="fund-detail"),
    path("fonds/<uuid:fund_id>/publier/", apis.FundPublishApi.as_view(), name="fund-publish"),
    path("fonds/<uuid:fund_id>/clore/", apis.FundCloseApi.as_view(), name="fund-close"),
    path("fonds/<uuid:fund_id>/nouvelles/", apis.FundNewsApi.as_view(), name="fund-news"),
    path("analyse/", apis.AnalysisApi.as_view(), name="analysis"),
    path("synthese/", apis.SummaryApi.as_view(), name="summary"),
    path("operations/", apis.OperationsApi.as_view(), name="operations"),
    path("operations/<uuid:donation_id>/rembourser/", apis.RefundApi.as_view(), name="refund"),
    path("operations/<uuid:donation_id>/donateur/", apis.DonorRevealApi.as_view(), name="donor-reveal"),
    path("quetes/fonds-proposes/", apis.MassFundsApi.as_view(), name="cash-funds"),
    path("quetes/", apis.CashCollectionListCreateApi.as_view(), name="cash"),
    path("quetes/<int:collection_id>/valider/", apis.CashCollectionValidateApi.as_view(), name="cash-validate"),
    path("quetes/<int:collection_id>/rejeter/", apis.CashCollectionRejectApi.as_view(), name="cash-reject"),
    path("compteurs/", apis_compteurs.CounterListCreateApi.as_view(), name="counters"),
    path("compteurs/<int:counter_id>/", apis_compteurs.CounterDetailApi.as_view(), name="counter-detail"),
    path("depots/", apis.CashDepositListCreateApi.as_view(), name="deposits"),
    path("remises-curie/", apis.RemittanceListCreateApi.as_view(), name="remittances"),
    path(
        "remises-curie/<int:remittance_id>/confirmer/", apis.RemittanceConfirmApi.as_view(), name="remittance-confirm"
    ),
    path(
        "remises-curie/<int:remittance_id>/contester/", apis.RemittanceContestApi.as_view(), name="remittance-contest"
    ),
    path("clotures/", apis.MonthClosingApi.as_view(), name="closings"),
    path("ajustements/", apis.AdjustmentApi.as_view(), name="adjustments"),
    path("incidents/", apis.IncidentListApi.as_view(), name="incidents"),
    path("incidents/<int:incident_id>/regulariser/", apis.IncidentResolveApi.as_view(), name="incident-resolve"),
    path("export/", apis.ExportApi.as_view(), name="export"),
    path("rapprochement/", apis.ReconciliationApi.as_view(), name="reconciliation"),
    path("quetes-imperees/", apis.ImpereeListCreateApi.as_view(), name="imperees"),
    path("quetes-imperees/<uuid:fund_id>/suivi/", apis.ImpereeFollowApi.as_view(), name="imperee-follow"),
    path("reversements/", apis.PayoutListApi.as_view(), name="payouts"),
]
