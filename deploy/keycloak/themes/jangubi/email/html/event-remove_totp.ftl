<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbRemoveTotpTitle") eyebrow=msg("jbSecurityEyebrow") preheader=msg("jbRemoveTotpTitle")>
<@layout.greeting/>
<@layout.p>${msg("jbRemoveTotpIntro", event.date?datetime?string("dd/MM/yyyy"), event.date?datetime?string("HH:mm"), event.ipAddress)}</@layout.p>
<@layout.note>${msg("jbRemoveTotpAdvice")}</@layout.note>
<@layout.signature/>
</@layout.emailLayout>
