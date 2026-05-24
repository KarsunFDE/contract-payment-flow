package com.karsunfde.contractflow.invoicereview.repository;

import com.karsunfde.contractflow.invoicereview.model.ContractModification;
import org.springframework.data.mongodb.repository.MongoRepository;

import java.util.List;

public interface ContractModificationRepository extends MongoRepository<ContractModification, String> {
    List<ContractModification> findByContractIdOrderByModNumberAsc(String contractId);
}
