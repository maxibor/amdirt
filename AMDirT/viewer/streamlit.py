from numpy import ALLOW_THREADS
import streamlit as st
import pandas as pd

from st_aggrid import GridOptionsBuilder, AgGrid, GridUpdateMode, DataReturnMode, JsCode
import argparse
import zipfile
import json
import os
from AMDirT import __version__
from AMDirT.core import (
    prepare_bibtex_file,
    prepare_eager_table,
    prepare_mag_table,
    prepare_accession_table,
    prepare_aMeta_table,
    is_merge_size_zero,
    get_amdir_tags,
)



st.set_page_config(
    page_title="AMDirT viewer",
    page_icon="https://raw.githubusercontent.com/SPAAM-community/AncientMetagenomeDir/master/assets/images/logos/spaam-AncientMetagenomeDir_logo_mini.png",
    layout="wide",
)

supported_archives = ["ENA", "SRA"]

if "compute" not in st.session_state:
    st.session_state.compute = False
if "force_validation" not in st.session_state:
    st.session_state.force_validation = False
if "table_name" not in st.session_state:
    st.session_state.table_name = None


def parse_args():
    parser = argparse.ArgumentParser("Run Streamlit app")
    parser.add_argument("-c", "--config", help="json config file", required=True)
    try:
        args = parser.parse_args()
    except SystemExit as e:
        os._exit(e.code)
    return args


args = parse_args()

tags = get_amdir_tags() + ["master"]

with open(args.config) as c:
    tables = json.load(c)
    samples = tables["samples"]
    libraries = tables["libraries"]

# Sidebar
with st.sidebar:
    st.markdown(
        """
<p style="text-align:center;"><img src="https://raw.githubusercontent.com/SPAAM-community/AncientMetagenomeDir/master/assets/images/logos/spaam-AncientMetagenomeDir_logo_colourmode.svg" alt="logo" width="50%"></p>
""",
        unsafe_allow_html=True,
    )
    st.write(f"# [AMDirT](https://github.com/SPAAM-community/AMDirT) viewer tool")
    st.write(f"\n Version: {__version__}")
    st.session_state.tag_name = st.selectbox(
        label="Select an AncientMetagenomeDir release", options=tags
    )
    options = ["No table selected"] + list(samples.keys())
    st.session_state.table_name = st.selectbox(label="Select a table", options=options)
    st.session_state.height = st.selectbox(
        "Number of rows to display", (10, 20, 50, 100, 200), index=2
    )
    st.session_state.dl_method = st.selectbox(
        label="Data download method", options=["curl", "nf-core/fetchngs", "aspera"]
    )
    if st.session_state.dl_method == "aspera":
        st.warning(
            "You will need to set the `${ASPERA_PATH}` environment variable. See [documentation](https://amdirt.readthedocs.io) for more information."
        )
    st.warning(
        f"Only {' and '.join(supported_archives)} archives are supported for now"
    )

if st.session_state.table_name != "No table selected":
    # Main content
    st.markdown(f"AncientMetagenomeDir release: `{st.session_state.tag_name}`")
    st.markdown(f"Displayed table: `{st.session_state.table_name}`")
    samp_url = samples[st.session_state.table_name].replace(
        "master", st.session_state.tag_name
    )
    lib_url = libraries[st.session_state.table_name].replace(
        "master", st.session_state.tag_name
    )
    df = pd.read_csv(
        samp_url,
        sep="\t",
    )
    library = pd.read_csv(
        lib_url,
        sep="\t",
    )
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(
        groupable=True,
        value=True,
        enableRowGroup=True,
        aggFunc="sum",
        editable=False,
        filterParams={"inRangeInclusive": "true"},
    )
    gb.configure_selection(selection_mode="multiple", use_checkbox=True)
    gb.configure_grid_options(checkboxSelection=True)

    gb.configure_pagination(
        enabled=True,
        paginationAutoPageSize=False,
        paginationPageSize=st.session_state.height,
    )
    gb.configure_column(
        "project_name",
        headerCheckboxSelection=True,
        headerCheckboxSelectionFilteredOnly=True,
    )
    gridOptions = gb.build()

    with st.form("Samples table") as f:
        st.markdown("Select samples to filter")
        df_mod = AgGrid(
            df,
            gridOptions=gridOptions,
            data_return_mode="filtered",
            update_mode="selection_changed",
        )
        if st.form_submit_button("Validate selection", type="primary"):
            if len(df_mod["selected_rows"]) == 0:
                st.error(
                    "You didn't select any sample! Please select at least one sample."
                )
            else:
                st.session_state.compute = True

    merge_is_zero = is_merge_size_zero(
        pd.DataFrame(df_mod["selected_rows"]), library, st.session_state.table_name
    )

    if (
        st.session_state.compute
        and not merge_is_zero
        and pd.DataFrame(df_mod["selected_rows"]).shape[0] != 0
    ):
        nb_sel_samples = pd.DataFrame(df_mod["selected_rows"]).shape[0]
        st.write(f"{nb_sel_samples } sample{'s'[:nb_sel_samples^1]} selected")
        st.session_state.force_validation = True

        placeholder = st.empty()

        with placeholder.container():
            (
                button_fastq, 
                button_samplesheet_eager, 
                button_samplesheet_mag, 
                button_samplesheet_ameta, 
                button_bibtex
            ) = st.columns(5)
            
            if st.session_state.force_validation:
                # Calculate the fastq file size of the selected libraries
                acc_table = prepare_accession_table(
                    pd.DataFrame(df_mod["selected_rows"]),
                    library,
                    st.session_state.table_name,
                    supported_archives,
                )["df"]
                total_size = (
                    acc_table["download_sizes"]
                    .apply(lambda r: sum([int(s) for s in r.split(";")]))
                    .sum(axis=0)
                )

                if total_size > 1e12:
                    total_size_str = f"{total_size / 1e12:.2f}TB"
                else:
                    total_size_str = f"{total_size / 1e9:.2f}GB"

                ############################
                ## FASTQ DOWNLOAD SCRIPTS ##
                ############################
                with button_fastq:
                    if st.session_state.dl_method == "nf-core/fetchngs":
                        st.download_button(
                            label=f"Download nf-core/fetchNGS input accession list",
                            help=f"approx. {total_size_str} of sequencing data selected",
                            data=prepare_accession_table(
                                pd.DataFrame(df_mod["selected_rows"]),
                                library,
                                st.session_state.table_name,
                                supported_archives,
                            )["df"]
                            .to_csv(sep="\t", header=False, index=False)
                            .encode("utf-8"),
                            file_name="ancientMetagenomeDir_accession_table.csv",
                        )
                    elif st.session_state.dl_method == "aspera":
                        st.download_button(
                            label="Download Aspera sample download script",
                            help=f"approx. {total_size_str} of sequencing data selected",
                            data=prepare_accession_table(
                                pd.DataFrame(df_mod["selected_rows"]),
                                library,
                                st.session_state.table_name,
                                supported_archives,
                            )["aspera_script"],
                            file_name="ancientMetagenomeDir_aspera_download_script.sh",
                        )
                    else:
                        st.download_button(
                            label="Download Curl sample download script",
                            help=f"approx. {total_size_str} of sequencing data selected",
                            data=prepare_accession_table(
                                pd.DataFrame(df_mod["selected_rows"]),
                                library,
                                st.session_state.table_name,
                                supported_archives,
                            )["curl_script"],
                            file_name="ancientMetagenomeDir_curl_download_script.sh",
                        )

                #################
                ## EAGER TABLE ##
                #################
                with button_samplesheet_eager:
                    st.download_button(
                        label="Download nf-core/eager input TSV",
                        data=prepare_eager_table(
                            pd.DataFrame(df_mod["selected_rows"]),
                            library,
                            st.session_state.table_name,
                            supported_archives,
                        )
                        .to_csv(sep="\t", index=False)
                        .encode("utf-8"),
                        file_name="ancientMetagenomeDir_eager_input.tsv",
                    )

                #######################
                ## NF-CORE/MAG TABLE ##
                #######################
                mag_table_single, mag_table_paired = prepare_mag_table(
                        pd.DataFrame(df_mod["selected_rows"]),
                        library,
                        st.session_state.table_name,
                        supported_archives,
                    )
                zip_file = zipfile.ZipFile(
                    'ancientMetagenomeDir_mag_input.zip', mode='w')
                if not mag_table_single.empty:
                    mag_table_single.to_csv(
                        "mag_input_single_table.csv", index=False
                        )
                    zip_file.write(
                        'mag_input_single_table.csv'
                        )
                if not mag_table_paired.empty:
                    mag_table_paired.to_csv(
                        "mag_input_paired_table.csv", index=False
                        )
                    zip_file.write(
                        'mag_input_paired_table.csv'
                        )
                zip_file.close()
                with open("ancientMetagenomeDir_mag_input.zip", "rb") as zip_file:
                    with button_samplesheet_mag:
                        st.download_button(
                            label="Download nf-core/mag input CSV",
                            data=zip_file,
                            file_name="ancientMetagenomeDir_mag_input.zip",
                            mime="application/zip",
                        )

                #################
                ## AMETA TABLE ##
                #################
                with button_samplesheet_ameta:
                    st.download_button(
                        label="Download aMeta input TSV",
                        data=prepare_aMeta_table(
                            pd.DataFrame(df_mod["selected_rows"]),
                            library,
                            st.session_state.table_name,
                            supported_archives,
                        )
                        .to_csv(sep="\t", index=False)
                        .encode("utf-8"),
                        file_name="ancientMetagenomeDir_aMeta_input.csv",
                    )


                #################
                ## BIBTEX FILE ##
                #################
                with button_bibtex:
                    st.download_button(
                        label="Download Citations as BibTex",
                        data=prepare_bibtex_file(pd.DataFrame(df_mod["selected_rows"])),
                        file_name="ancientMetagenomeDir_citations.bib",
                    )
                if st.button("Start New Selection", type="primary"):
                    st.session_state.compute = False
                    st.session_state.table_name = "No table selected"
                    st.session_state.force_validation = False
                    placeholder.empty()