<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbResetTitle") eyebrow=msg("jbSecurityEyebrow") preheader=msg("jbResetPreheader")>
<@layout.greeting/>
<@layout.p>${msg("jbResetIntro")}</@layout.p>
<@layout.button href=link label=msg("jbResetButton")/>
<@layout.note>${msg("jbLinkExpiry", linkExpirationFormatter(linkExpiration))} ${msg("jbResetIgnore")}</@layout.note>
<@layout.signature/>
</@layout.emailLayout>
