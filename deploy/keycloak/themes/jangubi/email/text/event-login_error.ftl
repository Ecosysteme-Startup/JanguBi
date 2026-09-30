<#ftl output_format="plainText">
<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbLoginErrorTitle") eyebrow=msg("jbSecurityEyebrow")>
${msg("jbLoginErrorIntro", event.date?datetime?string("dd/MM/yyyy"), event.date?datetime?string("HH:mm"), event.ipAddress)}

${msg("jbLoginErrorAdvice")}
</@layout.emailLayout>
