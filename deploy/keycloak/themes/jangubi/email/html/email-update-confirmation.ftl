<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbUpdateEmailTitle") eyebrow=msg("jbAccountEyebrow") preheader=msg("jbUpdateEmailPreheader")>
<@layout.greeting/>
<@layout.p>${msg("jbUpdateEmailIntro", newEmail)}</@layout.p>
<@layout.button href=link label=msg("jbUpdateEmailButton")/>
<@layout.muted>${msg("jbLinkExpiry", linkExpirationFormatter(linkExpiration))} ${msg("jbUpdateEmailIgnore")}</@layout.muted>
<@layout.signature/>
</@layout.emailLayout>
