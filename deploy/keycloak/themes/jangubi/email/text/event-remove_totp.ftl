<#ftl output_format="plainText">
<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbRemoveTotpTitle") eyebrow=msg("jbSecurityEyebrow")>
${msg("jbRemoveTotpIntro", event.date?datetime?string("dd/MM/yyyy"), event.date?datetime?string("HH:mm"), event.ipAddress)}

${msg("jbRemoveTotpAdvice")}
</@layout.emailLayout>
