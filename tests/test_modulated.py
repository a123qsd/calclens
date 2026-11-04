"""Average msCIF positions must never masquerade as an ordinary P1 slab."""

from pathlib import Path

import pytest

from slab_preflight import UnsupportedStructure, analyze_cif


GRAPHENE = (Path(__file__).resolve().parents[1] / "examples" / "graphene.cif").read_text()


@pytest.mark.parametrize(
    "declaration",
    [
        "_cell_modulation_dimension 1",
        "_cell.modulation_dimension 1",
        "_cell_modulation_dimension 0",  # Deliberately conservative about msCIF metadata.
        "_cell_modulation_dimension ?",
        "_space_group_ssg_name 'P 1(alpha,beta,gamma)0'",
        "_space_group_ssg.name 'P 1(alpha,beta,gamma)0'",
        "_space_group.ssg_name 'P 1(alpha,beta,gamma)0'",
        "_space_group_symop_ssg_operation_algebraic 'x1,x2,x3,x4'",
        "_space_group_symop_ssg.operation_algebraic 'x1,x2,x3,x4'",
        "_atom_site_displace_Fourier_param_cos 0.1",
        "_atom_site_displace_Fourier_param.cos 0.1",
        "_atom_site_occ_Fourier_param_sin 0.1",
        "_atom_site_U_Fourier_param_modulus 0.1",
        "_atom_site_displace_special_func_sawtooth_ax 0.2",
        "_atom_site_occ_special_func_crenel_c 0.2",
        "_cell_wave_vector_x 0.2",
        "_cell_wave_vector.x 0.2",
        "_cell_subsystem_code 1",
        "_atom_site_subsystem_code 1",
        "_atom_site_phason_coeff 0.1",
        "_atom_sites_modulation_global_phase_t_1 0.1",
        "_cell_reciprocal_basis_description 'modulated basis'",
    ],
)
def test_declared_modulation_is_not_silently_discarded(declaration):
    with pytest.raises(UnsupportedStructure, match="Modulated, superspace"):
        analyze_cif(GRAPHENE + "\n" + declaration + "\n")


def test_modulated_average_structure_reproduction():
    text = GRAPHENE + "\n_cell_modulation_dimension 1\n_space_group_ssg_name 'P 1(alpha,beta,gamma)0'\n"
    with pytest.raises(UnsupportedStructure, match="average site coordinates"):
        analyze_cif(text)


@pytest.mark.parametrize("tag", ["_space_group_name_h-m_ref", "_space_group.name_H-M_ref"])
def test_conflicting_reference_group_is_rejected(tag):
    with pytest.raises(UnsupportedStructure, match="Only P1"):
        analyze_cif(GRAPHENE + f"\n{tag} 'P -1'\n")


@pytest.mark.parametrize("tag", ["_space_group_name_h-m_ref", "_space_group.name_H-M_ref"])
def test_consistent_reference_group_is_supported(tag):
    report = analyze_cif(GRAPHENE + f"\n{tag} 'P 1'\n")
    assert report["atom_count"] == 2
    assert report["metrics"]["nuclei_gap_angstrom"] == pytest.approx(20.0)


def test_words_in_comments_or_prose_do_not_declare_modulation():
    report = analyze_cif(GRAPHENE + "\n# _cell_modulation_dimension 1\n_publ_section_comment 'No superspace or Fourier modulation used.'\n")
    assert report["atom_count"] == 2
