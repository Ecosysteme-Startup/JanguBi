<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbRemoveCredentialTitle") eyebrow=msg("jbSecurityEyebrow") preheader=msg("jbRemoveCredentialTitle")>
<@layout.greeting/>
<@layout.p>${msg("jbRemoveCredentialIntro", event.date?datetime?string("dd/MM/yyyy"), event.date?datetime?string("HH:mm"), event.ipAddress)}</@layout.p>
<@layout.note>${msg("jbCredentialAdvice")}</@layout.note>
<@layout.signature/>
</@layout.emailLayout>
