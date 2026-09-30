<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbVerifyTitle") eyebrow=msg("jbVerifyEyebrow") preheader=msg("jbVerifyPreheader")>
<@layout.greeting/>
<@layout.p>${msg("jbVerifyIntro")}</@layout.p>
<@layout.button href=link label=msg("jbVerifyButton")/>
<@layout.muted>${msg("jbLinkExpiry", linkExpirationFormatter(linkExpiration))} ${msg("jbVerifyIgnore")}</@layout.muted>
<@layout.signature/>
</@layout.emailLayout>
