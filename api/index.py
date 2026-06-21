from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import requests
import pg8000

# Estrutura de caminhos exata do repositório
app = Flask(__name__, static_folder='../../public', static_url_path='')
CORS(app)

VERCEL_BLOB_READ_WRITE_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN")
# Lê tanto a chave correta quanto qualquer variação com erro de digitação para garantir
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSOWORD")
DATABASE_URL = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL_NON_POOLING")


def obter_conexao():
    if not DATABASE_URL:
        raise ValueError("A string de conexão (POSTGRES_URL) não foi configurada na Vercel.")
    # Conectando via pg8000 para total compatibilidade com seu requirements.txt
    conn = pg8000.connect(dsn=DATABASE_URL)
    conn.autocommit = True
    return conn


def inicializar_infraestrutura_banco():
    if DATABASE_URL:
        try:
            conn = obter_conexao()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS produtos (
                    id_produto VARCHAR(255) PRIMARY KEY,
                    nome VARCHAR(255) NOT NULL,
                    preco NUMERIC(10, 2) NOT NULL,
                    categoria VARCHAR(100) NOT NULL,
                    foto TEXT NOT NULL,
                    visivel BOOLEAN DEFAULT TRUE
                );
            """)
            cursor.close()
            conn.close()
            print("🚀 Banco de dados inicializado.")
        except Exception as e:
            print(f"⚠️ Alerta banco: {str(e)}")


# Inicialização protegida para evitar erros de Cold Start no serverless
try:
    inicializar_infraestrutura_banco()
except Exception:
    pass


@app.route("/")
def index():
    return send_from_directory('../../public', 'index.html')


@app.route('/<path:path>')
def servir_arquivos_estaticos(path):
    return send_from_directory('../../public', path)


# ======================================================================
# ENDPOINT DE AUTENTICAÇÃO DO ADMINISTRADOR (CONSOLIDADO)
# ======================================================================
@app.route("/api/admin/login", methods=["POST"])
def login_administrador():
    dados = request.get_json() or {}
    senha_enviada = dados.get("senha")

    # Tratamento contra espaços em branco acidentais
    senha_sistema = ADMIN_PASSWORD.strip() if ADMIN_PASSWORD else None
    senha_digitada = senha_enviada.strip() if senha_enviada else None

    if senha_sistema and senha_digitada == senha_sistema:
        return jsonify({"status": "success", "token": "sessao_valida_lari_premium"}), 200
    
    return jsonify({"error": "Senha incorreta!"}), 401


# ======================================================================
# ENDPOINT DE UPLOAD DE FOTO (VERCEL BLOB)
# ======================================================================
@app.route("/api/upload", methods=["POST"])
def upload_foto():
    token_sessao = request.headers.get("Authorization")
    if token_sessao != "Bearer sessao_valida_lari_premium":
        return jsonify({"error": "Acesso não autorizado."}), 403

    if 'foto' not in request.files:
        return jsonify({"error": "Nenhum arquivo enviado."}), 400

    file = request.files['foto']
    if file.filename == '':
        return jsonify({"error": "Arquivo inválido."}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    content_type = file.content_type or "application/octet-stream"
    nome_id = f"produtos/produto_{os.urandom(4).hex()}{ext}"
    conteudo_binario = file.read()

    if not VERCEL_BLOB_READ_WRITE_TOKEN:
        return jsonify({"error": "Token de upload ausente."}), 500

    headers = {
        "Authorization": f"Bearer {VERCEL_BLOB_READ_WRITE_TOKEN}",
        "x-api-version": "1",
        "Content-Type": content_type
    }

    try:
        resposta = requests.put(f"https://blob.vercel-storage.com/{nome_id}", data=conteudo_binario, headers=headers)
        if resposta.status_code == 200:
            return jsonify({"url": resposta.json()["url"]}), 200
        return jsonify({"error": f"Erro Vercel Blob: {resposta.text}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ======================================================================
# ENDPOINT DE GERENCIAMENTO DE PRODUTOS (GET / POST)
# ======================================================================
@app.route("/api/produtos", methods=["GET", "POST"])
def gerenciar_produtos():
    if request.method == "POST":
        token_sessao = request.headers.get("Authorization")
        if token_sessao != "Bearer sessao_valida_lari_premium":
            return jsonify({"error": "Acesso não autorizado."}), 403

        dados = request.get_json() or {}
        id_produto = dados.get("id_produto")
        nome = dados.get("nome")
        preco = dados.get("preco")
        categoria = dados.get("categoria")
        foto = dados.get("foto")
        visivel = dados.get("visivel") if dados.get("visivel") is not None else True

        if not id_produto or not nome or preco is None:
            return jsonify({"error": "Campos incompletos."}), 400

        try:
            conn = obter_conexao()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO produtos (id_produto, nome, preco, categoria, foto, visivel)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id_produto) DO UPDATE 
                SET nome = EXCLUDED.nome, preco = EXCLUDED.preco, 
                    categoria = EXCLUDED.categoria, foto = EXCLUDED.foto, visivel = EXCLUDED.visivel;
            """, (str(id_produto).strip(), nome, float(preco), categoria, foto, bool(visivel)))
            cursor.close()
            conn.close()
            return jsonify({"status": "success"}), 201
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Método GET
    try:
        conn = obter_conexao()
        cursor = conn.cursor()
        cursor.execute("SELECT id_produto, nome, preco, categoria, foto, visivel FROM produtos ORDER BY nome ASC;")
        linhas = cursor.fetchall()
        cursor.close()
        conn.close()

        registros = []
        for l in linhas:
            registros.append({
                "id_produto": l[0],
                "nome": l[1],
                "preco": float(l[2]),
                "categoria": l[3],
                "foto": l[4],
                "visivel": l[5]
            })
        return jsonify(registros), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ======================================================================
# ENDPOINT DE EXCLUSÃO DE PRODUTO (DELETE)
# ======================================================================
@app.route("/api/produtos/<path:id_prod>", methods=["DELETE"])
def remover_produto_banco(id_prod):
    token_sessao = request.headers.get("Authorization")
    if token_sessao != "Bearer sessao_valida_lari_premium":
        return jsonify({"error": "Acesso não autorizado."}), 403

    id_limpo = str(id_prod).strip()

    try:
        conn = obter_conexao()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM produtos WHERE id_produto = %s;", (id_limpo,))
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": f"Produto {id_limpo} removido."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.errorhandler(404)
def rota_nao_encontrada(e):
    return jsonify({"error": "Endpoint não encontrado.", "status": "API Ativa"}), 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
