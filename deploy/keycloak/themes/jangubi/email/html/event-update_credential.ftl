<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbUpdateCredentialTitle") eyebrow=msg("jbSecurityEyebrow") preheader=msg("jbUpdateCredentialTitle")>
<@layout.greeting/>
<@layout.p>${msg("jbUpdateCredentialIntro", event.date?datetime?string("dd/MM/yyyy"), event.date?datetime?string("HH:mm"), event.ipAddress)}</@layout.p>
<@layout.note>${msg("jbCredentialAdvice")}</@layout.note>
<@layout.signature/>
</@layout.emailLayout>
