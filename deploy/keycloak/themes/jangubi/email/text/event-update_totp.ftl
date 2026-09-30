<#ftl output_format="plainText">
<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbUpdateTotpTitle") eyebrow=msg("jbSecurityEyebrow")>
${msg("jbUpdateTotpIntro", event.date?datetime?string("dd/MM/yyyy"), event.date?datetime?string("HH:mm"), event.ipAddress)}

${msg("jbUpdateTotpAdvice")}
</@layout.emailLayout>
