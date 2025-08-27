import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import streamlit as st
from pathlib import Path
from backend.src.techsheet_processor import process_techsheet_request

# Calculate project root dynamically based on this file's location
# Assumes techsheet_page.py is in frontend/pages
PROJECT_ROOT = Path(__file__).parent.parent.parent
TEMPLATE_DOCX_PATH = PROJECT_ROOT / "techsheet" / "Fiche_Technique_Modele.docx"

# Define available domains
domains = [
    "pointp.fr", "cedeo.fr", "se.com"
]

# Initialize session state for results
if 'result' not in st.session_state:
    st.session_state.result = None

st.set_page_config(
    page_title="Générateur de Fiche Technique",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
    <style>
    .reportview-container {
        background: #f0f2f6
    }
    .sidebar .sidebar-content {
        background: #f0f2f6
    }
    header .main .block-container {
        padding-top: 2rem;
        padding-right: 2rem;
        padding-left: 2rem;
        padding-bottom: 2rem;
    }
    .css-1d391kg:hover {
        color: #e6e6e6;
        background-color: #31333F;
        border-color: #31333F;
    }
    .stButton>button {
        color: #fff;
        background-color: #4CAF50;
        border-radius: 5px;
        padding: 10px 20px;
        font-size: 16px;
        border: none;
        cursor: pointer;
    }
    .stButton>button:hover {
        background-color: #45a049;
    }
    .stProgress > div > div {
        background-color: #4CAF50 !important;
    }
    .stAlert {
        padding: 1rem;
        border-radius: 0.5rem;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("📄 Générateur de Fiche Technique")
st.write("Entrez les informations du produit pour générer sa fiche technique.")

# Input fields
with st.form("techsheet_form"):
    titre_produit = st.text_input("Titre/nom du produit", help="Ex: Disjoncteur différentiel, Chauffe-eau")
    marque = st.text_input("Marque", help="Ex: Legrand, Atlantic")
    reference = st.text_input("Référence", help="Ex: 411632, 001234")
    selected_domains = st.multiselect(
        "Nom de domaine (laisser vide pour tous les sites)",
        options=domains,
        default=[]
    )

    submitted = st.form_submit_button("Générer la Fiche Technique")

    if submitted:
        if not titre_produit:
            st.error("Veuillez entrer le titre/nom du produit.")
        else:
            with st.spinner("Génération de la fiche technique en cours..."):
                try:
                    result = process_techsheet_request(
                        titre_produit, marque, reference, str(TEMPLATE_DOCX_PATH), selected_domains
                    )
                    st.session_state.result = result # Store result in session state

                    if result["status"] == "success":
                        st.success("Fiche technique générée avec succès !")
                        st.write("### Récapitulatif de la recherche")
                        st.markdown(f"**Site source**: {result['url_source']}")
                        st.markdown(f"**URL produit**: [{result['best_url']}]({result['best_url']})")
                        st.markdown(f"**Temps d'exécution**: {result['execution_time']:.2f} secondes")
                        st.markdown(f"**ID de la requête**: {result['request_id']}")

                        st.write("### Données extraites")
                        data = result["extracted_data"]
                        if data.get("TITRE"):
                            st.markdown(f"**Titre**: {data['TITRE']}")
                        if data.get("REFERENCE"):
                            st.markdown(f"**Référence**: {data['REFERENCE']}")
                        if data.get("DESCRIPTION"):
                            st.markdown(f"**Description**: {data['DESCRIPTION']}")
                        if data.get("AVANTAGES"):
                            st.markdown("**Avantages**:")
                            for item in data["AVANTAGES"]:
                                st.markdown(f"- {item}")
                        if data.get("UTILISATION"):
                            st.markdown("**Utilisation**:")
                            for item in data["UTILISATION"]:
                                st.markdown(f"- {item}")
                        if data.get("CARACTERISTIQUES TECHNIQUES"):
                            st.markdown("**Caractéristiques techniques**:")
                            for k, v in data["CARACTERISTIQUES TECHNIQUES"].items():
                                st.markdown(f"- **{k}**: {v}")

                    else:
                        st.error(f"Erreur lors de la génération: {result['message']}")
                        st.session_state.result = None # Clear result on error

                except Exception as e:
                    st.error(f"Une erreur inattendue est survenue: {e}")
                    st.exception(e)
                    st.session_state.result = None # Clear result on error

# Display download buttons outside the form, after processing
if st.session_state.result and st.session_state.result["status"] == "success":
    result = st.session_state.result
    st.write("### Fichiers générés")
    if result["image_path"] and os.path.exists(result["image_path"]):
        st.image(result["image_path"], caption="Image Produit", width=200)

    if result["generated_docx"] and os.path.exists(result["generated_docx"]):
        with open(result["generated_docx"], "rb") as file:
            st.download_button(
                label="Télécharger la Fiche Technique (DOCX)",
                data=file,
                file_name=os.path.basename(result["generated_docx"]),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
    else:
        st.warning("Fichier DOCX non généré ou introuvable.")

    if result["downloaded_pdfs"]:
        st.markdown("**PDF(s) original(aux)**:")
        for i, pdf_path in enumerate(result["downloaded_pdfs"]):
            if os.path.exists(pdf_path):
                with open(pdf_path, "rb") as file:
                    st.download_button(
                        label=f"Télécharger {os.path.basename(pdf_path)}",
                        data=file,
                        file_name=os.path.basename(pdf_path),
                        mime="application/pdf",
                        key=f"{pdf_path}_{i}" # Changed key here
                    )
            else:
                st.warning(f"PDF original introuvable: {os.path.basename(pdf_path)}")
    else:
        st.info("Aucun PDF original détecté.")
