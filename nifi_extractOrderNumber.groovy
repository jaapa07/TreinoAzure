import groovy.json.JsonSlurper
import groovy.xml.MarkupBuilder
import org.apache.commons.io.IOUtils
import java.nio.charset.StandardCharsets

// Pega o FlowFile de entrada
def flowFile = session.get()
if (!flowFile) return

def extractOrderNumber(String observacao) {
    if (!observacao) return null
    def matcher = observacao =~ /OC:\s*(\d+)/
    return matcher ? matcher[0][1] : null
}

try {
    def conteudo = ''
    session.read(flowFile, { inputStream ->
        conteudo = IOUtils.toString(inputStream, StandardCharsets.UTF_8)
    } as InputStreamCallback)

    def json = new JsonSlurper().parseText(conteudo)

    def writer = new StringWriter()
    def xml = new MarkupBuilder(writer)
    xml.mkp.xmlDeclaration(version: '1.0', encoding: 'UTF-8')

    xml.embarque {
        dataEmbarque(json.dataEmbarque)
        Documentos {
            json.Documentos?.each { doc ->
                Documento {
                    doc.each { chave, valor ->
                        if (chave == 'Itens') {
                            Itens {
                                valor?.each { item ->
                                    Item {
                                        item.each { k, v -> "$k"(v) }
                                    }
                                }
                            }
                        } else if (chave in ['enderecoEntrega', 'remetente', 'destinatario', 'emitente', 'transportadora']) {
                            "$chave" {
                                valor?.each { k, v -> "$k"(v) }
                            }
                        } else {
                            "$chave"(valor)
                        }
                    }
                    ocExtraida(extractOrderNumber(doc.observacao as String) ?: '')
                }
            }
        }
    }

    def xmlResultado = writer.toString()

    flowFile = session.write(flowFile, { outputStream ->
        outputStream.write(xmlResultado.getBytes(StandardCharsets.UTF_8))
    } as OutputStreamCallback)

    flowFile = session.putAttribute(flowFile, 'mime.type', 'application/xml')

    session.transfer(flowFile, REL_SUCCESS)

} catch (Exception e) {
    log.error("Erro ao processar FlowFile: ${e.message}", e)
    session.transfer(flowFile, REL_FAILURE)
}
