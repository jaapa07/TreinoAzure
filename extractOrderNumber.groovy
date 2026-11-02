import groovy.json.JsonSlurper
import groovy.xml.MarkupBuilder

def extractOrderNumber(String observacao) {
    if (!observacao) return null

    def matcher = observacao =~ /OC:\s*(\d+)/
    return matcher ? matcher[0][1] : null
}

def processarEmbarque(String jsonText) {
    def json = new JsonSlurper().parseText(jsonText)

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

    return writer.toString()
}

// --- Teste ---
def jsonExemplo = '''
{
  "dataEmbarque": "14/05/24",
  "numeroEmbarque": 198582,
  "placa": "XXX9999",
  "Documentos": [
    {
      "observacao": "OPERACAO DESTINADA A CONSUMIDOR FINAL. | OC: 131563 |",
      "numeroNotaFiscal": "0346988",
      "numeroDocumento": 131563,
      "valor": 13532.1,
      "enderecoEntrega": {
        "uf": "MG",
        "cidade": "BELO HORIZONTE",
        "cep": "30170080"
      }
    },
    {
      "observacao": "Base de Cálculo do ICMS Reduzida - Pedido cliente: 2180450",
      "numeroNotaFiscal": "0346999",
      "numeroDocumento": 2180450,
      "valor": 5000.0,
      "enderecoEntrega": {
        "uf": "SP",
        "cidade": "SAO PAULO",
        "cep": "01310100"
      }
    }
  ]
}
'''

println processarEmbarque(jsonExemplo)
