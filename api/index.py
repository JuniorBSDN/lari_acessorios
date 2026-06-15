from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

# Estrutura de caminhos do repositório (api/api/index.py sobe para public na raiz)
app = Flask(__name__, static_folder='../../public', static_url_path='')
CORS(app)

VERCEL_BLOB_READ_WRITE_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
DATABASE_URL = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL_NON_POOLING")


def obter_conexao():
    if not DATABASE_URL:
        raise ValueError("A string de conexão (POSTGRES_URL) não foi configurada na Vercel.")
    conn = psycopg2.connect(DATABASE_URL, sslmode="require", cursor_factory=RealDictCursor)
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
            print("🚀 Banco de dados verificado com sucesso.")
        except Exception as e:
            print(f"⚠️ Inicialização do banco: {str(e)}")


inicializar_infraestrutura_banco()


@app.route("/")
def index():
    return send_from_directory('../../public', 'index.html')


@app.route('/<path:path>')
def servir_arquivos_estaticos(path):
    return send_from_directory('../../public', path)


# ======================================================================
# LOGIN ADMIN
# ======================================================================
@app.route("/api/login", methods=["POST"])
@app.route("/api/admin/login", methods=["POST"])
def login_administrador():
    dados = request.get_json() or {}
    senha = str(dados.get("senha", "")).strip()

    if not ADMIN_PASSWORD:
        return jsonify({
            "authenticated": False,
            "error": "ADMIN_PASSWORD não configurada."
        }), 500

    if senha == ADMIN_PASSWORD:
        return jsonify({
            "authenticated": True,
            "status": "success",
            "token": "Bearer sessao_valida_lari_premium"
        }), 200

    return jsonify({
        "authenticated": False,
        "error": "Senha incorreta."
    }), 401

# ======================================================================
# ENDPOINT DE UPLOAD DE FOTO (VERCEL BLOB)
# ======================================================================
@app.route("/api/upload", methods=["POST"])
def upload_foto():
    if not validar_sessao():
    return jsonify({"error": "Acesso não autorizado."}), 403

    if 'foto' not in request.files:
        return jsonify({"error": "Nenhum arquivo de imagem enviado."}), 400

    file = request.files['foto']
    if file.filename == '':
        return jsonify({"error": "Nome de arquivo inválido."}), 400

    ext = os.path.splitext(file.filename)[1].lower()

    permitidos = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp"
    }

if ext not in permitidos:
    return jsonify({
        "error": "Formato inválido."
    }), 400
    
    
    content_type = file.content_type or "application/octet-stream"
    nome_id = f"produtos/produto_{os.urandom(4).hex()}{ext}"
    conteudo_binario = file.read()
    if len(conteudo_binario) > 5 * 1024 * 1024:
    return jsonify({
        "error": "Imagem maior que 5MB."
    }), 400
    

    if not VERCEL_BLOB_READ_WRITE_TOKEN:
        return jsonify({"error": "Token BLOB_READ_WRITE_TOKEN ausente."}), 500

    headers = {
        "Authorization": f"Bearer {VERCEL_BLOB_READ_WRITE_TOKEN}",
        "x-api-version": "1",
        "Content-Type": content_type
    }

    try:
        resposta = requests.put(f"https://blob.vercel-storage.com/{nome_id}", data=conteudo_binario, headers=headers)
        if resposta.status_code == 200:
            return jsonify({"url": resposta.json()["url"]}), 200
        return jsonify({"error": f"Erro na API Vercel Blob: {resposta.text}"}), 500
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
            return jsonify({"error": "Metadados essenciais incompletos."}), 400

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

    # Execução do método GET
    try:
        conn = obter_conexao()
        cursor = conn.cursor()
        cursor.execute("SELECT id_produto, nome, preco, categoria, foto, visivel FROM produtos ORDER BY nome ASC;")
        registros = cursor.fetchall()
        cursor.close()
        conn.close()

        for r in registros:
            r['preco'] = float(r['preco'])

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
        return jsonify({"status": "success", "message": f"Produto {id_limpo} removido com sucesso."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.errorhandler(404)
def rota_nao_encontrada(e):
    return jsonify({"error": "Endpoint não encontrado no subsistema de backend.", "status": "API Ativa"}), 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
