<#ftl output_format="plainText">
<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbUpdatePasswordTitle") eyebrow=msg("jbSecurityEyebrow")>
${msg("jbUpdatePasswordIntro", event.date?datetime?string("dd/MM/yyyy"), event.date?datetime?string("HH:mm"), event.ipAddress)}

${msg("jbUpdatePasswordAdvice")}
</@layout.emailLayout>
