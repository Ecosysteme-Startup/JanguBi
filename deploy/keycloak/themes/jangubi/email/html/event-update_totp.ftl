<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbUpdateTotpTitle") eyebrow=msg("jbSecurityEyebrow") preheader=msg("jbUpdateTotpTitle")>
<@layout.greeting/>
<@layout.p>${msg("jbUpdateTotpIntro", event.date?datetime?string("dd/MM/yyyy"), event.date?datetime?string("HH:mm"), event.ipAddress)}</@layout.p>
<@layout.note>${msg("jbUpdateTotpAdvice")}</@layout.note>
<@layout.signature/>
</@layout.emailLayout>
