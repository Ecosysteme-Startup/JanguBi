<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbLoginErrorTitle") eyebrow=msg("jbSecurityEyebrow") preheader=msg("jbLoginErrorTitle")>
<@layout.greeting/>
<@layout.p>${msg("jbLoginErrorIntro", event.date?datetime?string("dd/MM/yyyy"), event.date?datetime?string("HH:mm"), event.ipAddress)}</@layout.p>
<@layout.note>${msg("jbLoginErrorAdvice")}</@layout.note>
<@layout.signature/>
</@layout.emailLayout>
