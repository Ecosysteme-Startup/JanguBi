<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbUpdatePasswordTitle") eyebrow=msg("jbSecurityEyebrow") preheader=msg("jbUpdatePasswordTitle")>
<@layout.greeting/>
<@layout.p>${msg("jbUpdatePasswordIntro", event.date?datetime?string("dd/MM/yyyy"), event.date?datetime?string("HH:mm"), event.ipAddress)}</@layout.p>
<@layout.note>${msg("jbUpdatePasswordAdvice")}</@layout.note>
<@layout.signature/>
</@layout.emailLayout>
