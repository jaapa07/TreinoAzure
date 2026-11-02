import groovy.json.JsonSlurper
import groovy.json.JsonOutput

def extractOrderNumber(String observacao) {
    if (!observacao) return null

    def matcher = observacao =~ /OC:\s*(\d+)/
    return matcher ? matcher[0][1] : null
}

def processarEmbarque(String jsonText) {
    def json = new JsonSlurper().parseText(jsonText)

    json.Documentos?.each { doc ->
        doc.ocExtraida = extractOrderNumber(doc.observacao as String)
    }

    return [
        dataEmbarque: json.dataEmbarque,
        Documentos  : json.Documentos
    ]
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
      "valor": 13532.1
    },
    {
      "observacao": "Base de Cálculo do ICMS Reduzida - Pedido cliente: 2180450",
      "numeroNotaFiscal": "0346999",
      "numeroDocumento": 2180450,
      "valor": 5000.0
    }
  ]
}
'''

def resultado = processarEmbarque(jsonExemplo)
println JsonOutput.prettyPrint(JsonOutput.toJson(resultado))
