package com.karsunfde.contractflow.invoicereview.controller;

import com.karsunfde.contractflow.invoicereview.model.ContractModification;
import com.karsunfde.contractflow.invoicereview.repository.ContractModificationRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * Bulk listing controller for {@link ContractModification} entries.
 *
 * Pair-unique brownfield-debt (Pair 2 / D-059):
 *   - rel-bulk-endpoint-no-pagination — {@link #listAll()} returns
 *     {@code repo.findAll()} with no pagination. With 100k+ mod rows
 *     across the contract lifecycle, this is an OOM trigger.
 *     Cohort fixes in W5 (AIOps day) with {@code Pageable} + a hard
 *     server-side cap.
 *
 * NB: name is intentionally {@code ContractModificationListController} (not
 * {@code ContractModificationController}) to avoid colliding with the
 * pair's renamed primary-entity controller in
 * contract-modification-service. The legacy {@link ContractModification}
 * model + repo carried into this service from acquire-gov's D-060
 * inventory is what's listed here.
 */
@RestController
@RequestMapping("/api/contract-modification-list")
public class ContractModificationListController {

    private final ContractModificationRepository repo;

    @Autowired
    public ContractModificationListController(ContractModificationRepository repo) {
        this.repo = repo;
    }

    /**
     * Bulk list endpoint. ⚠ PAIR-UNIQUE DEBT: rel-bulk-endpoint-no-pagination.
     * Returns every modification across every contract — no Pageable, no
     * cap, no streaming. Triggers OOM at scale.
     *
     * fixed_looks_like:
     *   @GetMapping("/contract-modifications")
     *   public Page<ContractModification> list(@PageableDefault(size=50) Pageable p) {
     *     return repo.findAll(p);
     *   }
     */
    @GetMapping("/all")
    public List<ContractModification> listAll() {
        // ⚠ no pagination — 100k rows → OOM
        return repo.findAll();
    }
}
