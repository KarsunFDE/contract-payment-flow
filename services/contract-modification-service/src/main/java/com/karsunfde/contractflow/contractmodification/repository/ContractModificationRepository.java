package com.karsunfde.contractflow.contractmodification.repository;

import com.karsunfde.contractflow.contractmodification.model.ContractModification;
import org.springframework.data.mongodb.repository.MongoRepository;

import java.util.List;

/**
 * ⚠ DELIBERATE — Item 10:
 *   {@code findAll()} returns contractModifications across ALL agencies. There is a
 *   {@code findByAgencyId} method declared below — it just isn't called from
 *   {@code ContractModificationService}. Cohort fixes in W2 Wed by switching all
 *   reads to {@code findByAgencyId} (and resolving agency from JWT).
 */
public interface ContractModificationRepository extends MongoRepository<ContractModification, String> {

    /** Declared but not used — the cohort discovers and wires this up. */
    List<ContractModification> findByAgencyId(String agencyId);
}
