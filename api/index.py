from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

# Variáveis lidas de forma segura do painel da Vercel
VERCEL_BLOB_READ_WRITE_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")  # Senha padrão caso esqueça de definir


@app.route("/api/login", methods=["POST"])
def login_admin():
    dados = request.get_json() or {}
    senha_enviada = dados.get("senha")

    if not senha_enviada:
        return jsonify({"authenticated": False, "error": "Senha não fornecida."}), 400

    if senha_enviada == ADMIN_PASSWORD:
        return jsonify({"authenticated": True, "token": "sessao_valida_lari_premium"}), 200
    else:
        return jsonify({"authenticated": False, "error": "Senha incorreta."}), 401


@app.route("/api/upload", methods=["POST"])
def upload_foto():
    # Validação básica de token de sessão para proteger o endpoint de upload
    token_sessao = request.headers.get("Authorization")
    if token_sessao != "Bearer sessao_valida_lari_premium":
        return jsonify({"error": "Acesso não autorizado."}), 403

    if 'foto' not in request.files:
        return jsonify({"error": "Nenhum arquivo enviado no formulário."}), 400

    file = request.files['foto']
    if file.filename == '':
        return jsonify({"error": "Arquivo sem nome válido."}), 400

    ext = os.path.splitext(file.filename)[1]
    nome_id = f"produto_{os.urandom(4).hex()}{ext}"
    conteudo_binario = file.read()

    if not VERCEL_BLOB_READ_WRITE_TOKEN:
        return jsonify({"error": "Token do Vercel Blob não configurado."}), 500

    headers = {
        "Authorization": f"Bearer {VERCEL_BLOB_READ_WRITE_TOKEN}",
        "x-api-version": "1",
    }

    url_destino_blob = f"https://blob.vercel-storage.com/{nome_id}"

    try:
        resposta_vercel = requests.put(url_destino_blob, data=conteudo_binario, headers=headers)
        if resposta_vercel.status_code == 200:
            dados_retorno = resposta_vercel.json()
            return jsonify({"url": dados_retorno["url"]}), 200
        else:
            return jsonify({"error": f"Erro na API da Vercel: {resposta_vercel.text}"}), 500

    except Exception as e:
        return jsonify({"error": f"Falha interna no servidor: {str(e)}"}), 500


@app.route("/api", defaults={"path": ""})
@app.route("/api/<path:path>")
def catch_all(path):
    return jsonify({"status": "API LariAcessórios ativa"}), 200
