def extractOrderNumber(String observacao) {
    if (!observacao) return null

    def matcher = observacao =~ /OC:\s*(\d+)/
    return matcher ? matcher[0][1] : null
}

// Exemplos de uso
def exemplos = [
    "OPERACAO DESTINADA A CONSUMIDOR FINAL. VALOR DO ICMS DIFAL DESTINO R$ ,00 VALOR DO ICMS DIFAL REMETENTE R$,00 | OC: 131563 |",
    "NOTA FISCAL DE VENDA | OC: 999001 | CLIENTE: JOAO",
    "SEM ORDEM DE COMPRA",
    "OC:456789",
    "OC: 000123 | OUTRO DADO"
]

exemplos.each { obs ->
    def numero = extractOrderNumber(obs)
    if (numero) {
        println "OC encontrada: ${numero} | observacao: ${obs}"
    } else {
        println "OC nao encontrada    | observacao: ${obs}"
    }
}
